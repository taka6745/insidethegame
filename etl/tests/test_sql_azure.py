"""Azure SQL side of the Stream Analytics path (sql/azure/asa-progress.sql) on SQL Server: the job's rows,
inserted as independent output batches in an adversarial order, give the reference watermark, status and
statsAtSeq (after the SPADL post-processor, which Azure runs as its own app); purges and tombstones hold against
later inserts. Same disposable server as test_sql_catalogue."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import sql_server
import v2_stream
from local_stream.repository import MATCH_TABLES, SqlRepository, sql_value
from reference import pipeline
from spadl.worker import SpadlRepository, SpadlWorker
from sql_server import query
from test_catalogue import outputs, reference

pytestmark = sql_server.enabled
ETL = Path(__file__).resolve().parents[1]
SCRIPTS = [*sorted((ETL / "sql" / "migrations").glob("*.sql")), *sorted((ETL / "sql" / "azure").glob("*.sql"))]


@pytest.fixture
def connect():
    """A fresh database as on Azure: migrations plus the Azure scripts, no local worker tables."""
    yield from sql_server.database("itg_azure", SCRIPTS)


def insert(connect, table, rows, batch=500, parallel=False):
    """One transaction per batch, like a Stream Analytics output flush (parallel: on a connection of its own)."""
    conn = connect() if parallel else connect.shared
    try:
        for i in range(0, len(rows), batch):
            chunk, columns = rows[i:i + batch], list(rows[0])
            values = ", ".join(["(" + ", ".join(["%s"] * len(columns)) + ")"] * len(chunk))
            conn.cursor().execute(f"INSERT dbo.{table} ({', '.join(columns)}) VALUES {values}",
                                  tuple(sql_value(c, r[c]) for r in chunk for c in columns))
            conn.commit()
    finally:
        if parallel:
            conn.close()


def progress(connect, match_id):
    mark = query(connect, "SELECT seq FROM dbo.matchWatermarks WHERE matchId = %s", match_id)
    status = query(connect, "SELECT status FROM dbo.matches WHERE matchId = %s", match_id)
    return (mark[0]["seq"] if mark else 0), (status[0]["status"] if status else None)


def counts(connect, match_id):
    return {t: query(connect, f"SELECT COUNT(*) AS n FROM dbo.{t} WHERE matchId = %s", match_id)[0]["n"]
            for t in (*[t for t in MATCH_TABLES if not t.startswith("local")], "matchWatermarks")}


def test_marks_become_the_reference_watermark_in_any_output_order(connect):
    stream = v2_stream.build()
    match_id, rows, marks = stream[0]["matchId"], pipeline.stream_outputs(stream, 60), pipeline.progress_marks(stream)
    final = len(rows["canonicalEvents"])
    stored = {t: [] for t in pipeline.TABLES}

    def write(table, part):
        insert(connect, table, part)
        stored[table] += part
        expect = pipeline.watermark(marks, stored, match_id)
        assert progress(connect, match_id) == (expect, pipeline.match_status(rows["matches"][0], stored["canonicalEvents"], expect))

    insert(connect, "matchProgressMarks", marks)  # Marks first: nothing they cover is committed yet.
    assert progress(connect, match_id) == (0, None)
    for table in ("matches", "matchTeams", "matchPlayers", "keyEvents", "minuteStats"):
        write(table, rows[table])
    write("canonicalEvents", rows["canonicalEvents"])
    write("possessionSamples", rows["possessionSamples"][:3000])
    raw = rows["rawEvents"]
    write("rawEvents", raw[:1200])
    seq, status = progress(connect, match_id)
    assert 0 < seq < final and status == "live"
    write("rawEvents", raw[1200:])
    write("possessionSamples", rows["possessionSamples"][3000:])
    assert progress(connect, match_id) == (final, "finished")
    assert not query(connect, "SELECT * FROM dbo.matchProgressMarks WHERE matchId = %s", match_id)  # Consumed.
    assert query(connect, "EXEC dbo.statsAtSeq @matchId = %s, @seq = %s", match_id, 1) == []  # SPADL lags: retry.
    SpadlWorker(SpadlRepository(connect)).step()
    expected = outputs(stream)
    for s in (1, 2400, final):
        got = query(connect, "EXEC dbo.statsAtSeq @matchId = %s, @seq = %s", match_id, s)
        assert got == reference(s, expected, final), s
    for table in ("matchTeams", "matchPlayers", "canonicalEvents", "rawEvents"):
        assert query(connect, f"SELECT COUNT(*) AS n FROM dbo.{table}")[0]["n"] == len(rows[table]), table
    # The trigger keeps eventSeq: snapshot reads bound MA3 rows by this indexed column.
    assert query(connect, """SELECT COUNT(*) AS n FROM dbo.rawEvents
                             WHERE eventSeq IS NULL OR eventSeq <> JSON_VALUE(payload, '$.eventSeq')""")[0]["n"] == 0
    assert query(connect, "SELECT INDEXPROPERTY(OBJECT_ID('dbo.rawEvents'), 'IX_rawEvents_eventSeq', 'IndexID') AS i")[0]["i"]


def test_purge_and_tombstones_hold_against_later_inserts(connect):
    a, b = v2_stream.build("0000aaaa"), v2_stream.build("0000bbbb", fixture="arsenal-liverpool")
    out = {s[0]["matchId"]: (pipeline.stream_outputs(s, 60), pipeline.progress_marks(s)) for s in (a, b)}

    def deliver(match_id, upto=None):
        rows, marks = out[match_id]
        for table in pipeline.TABLES:
            if rows[table][:upto]:
                insert(connect, table, rows[table][:upto])
        insert(connect, "matchProgressMarks", marks[:upto])

    for match_id in out:
        deliver(match_id, 2000)
    a_id, b_id = a[0]["matchId"], b[0]["matchId"]
    assert progress(connect, a_id)[0] > 0
    assert set(SpadlWorker(SpadlRepository(connect)).step()) == {a_id, b_id}
    assert counts(connect, a_id)["spadlActions"] > 0
    assert SqlRepository(connect).purge(a_id)[0] == [a_id]
    assert set(counts(connect, a_id).values()) == {0}
    deliver(a_id, 3000)  # In-flight (2000-2999) and redelivered (0-1999) rows of the purged match are dropped.
    SpadlWorker(SpadlRepository(connect)).step()
    assert set(counts(connect, a_id).values()) == {0}
    assert counts(connect, b_id)["canonicalEvents"] == 2000

    cutoff = datetime(2026, 10, 20, 15, 30, tzinfo=timezone.utc)
    ids, _ = SqlRepository(connect).purge(None, cutoff)  # Purge all: tombstones plus the cut-off.
    assert ids == [b_id] and set(counts(connect, b_id).values()) == {0}
    late = v2_stream.build("0000cccc")  # MA1 stamped 14:59, before the cut-off: never created.
    fresh = v2_stream.build("0000dddd", kickoff=cutoff + timedelta(minutes=5))
    for s in (late, fresh):
        out[s[0]["matchId"]] = pipeline.stream_outputs(s, 60), pipeline.progress_marks(s)
        deliver(s[0]["matchId"], 500)
    assert set(counts(connect, late[0]["matchId"]).values()) == {0}
    assert query(connect, "SELECT 1 AS x FROM dbo.purgedMatches WHERE matchId = %s", late[0]["matchId"])
    assert counts(connect, fresh[0]["matchId"])["canonicalEvents"] == 500 and progress(connect, fresh[0]["matchId"])[0] > 0
    assert query(connect, "SELECT COUNT(*) AS n FROM dbo.statDefinitions")[0]["n"] == 42  # Configuration stays.


def test_concurrent_output_batches_reach_the_final_watermark(connect):
    """Outputs flush in parallel; per-match locks make the last committer see every batch."""
    from concurrent.futures import ThreadPoolExecutor

    streams = [v2_stream.build("0000eeee", fixture=f) for f in v2_stream.FIXTURES[1:]]
    jobs = []
    for s in streams:
        rows = pipeline.stream_outputs(s, 60)
        insert(connect, "matches", rows["matches"])
        jobs += [("matchProgressMarks", pipeline.progress_marks(s))]
        jobs += [(t, rows[t]) for t in ("canonicalEvents", "possessionSamples", "rawEvents", "keyEvents", "minuteStats")]
    with ThreadPoolExecutor(len(jobs)) as pool:
        list(pool.map(lambda job: insert(connect, job[0], job[1], batch=250, parallel=True), jobs))
    for s in streams:
        events = sum(m.get("type") == "MatchEvent" for m in s)
        assert progress(connect, s[0]["matchId"]) == (events, "finished")
