"""SQL Server: migrations, the local stream worker, the SPADL post-processor and statsAtSeq against the references.

Needs a disposable SQL Server (never a shared stack); each test creates and drops its own database (sql_server.py):
    ETL_TEST_SQL_PASSWORD=… [ETL_TEST_SQL_HOST=127.0.0.1 ETL_TEST_SQL_PORT=1433] pytest tests/test_sql_catalogue.py
"""
import json
from datetime import timedelta
from pathlib import Path

import pytest

import sql_server
import v2_stream
from local_stream.repository import MATCH_TABLES, SqlRepository
from local_stream.worker import StreamWorker
from reference import spadl, trends
from spadl.worker import SpadlRepository, SpadlWorker
from sql_server import query
from test_catalogue import golden, outputs, reference

pytestmark = sql_server.enabled
ETL = Path(__file__).resolve().parents[1]
SCRIPTS = [*sorted((ETL / "sql" / "migrations").glob("*.sql")), ETL / "local_stream" / "state.sql"]


@pytest.fixture
def connect():
    """A fresh database with every migration and the worker's state tables applied."""
    yield from sql_server.database("itg_test", SCRIPTS)


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def feed(worker, messages, batch=250, start=0):
    for i in range(0, len(messages), batch):
        worker.handle("0", [(start + i + j, json.dumps(m)) for j, m in enumerate(messages[i:i + batch])])


def settle(worker, clock):
    clock.now += 1000
    worker.handle("0", [])


def stats(connect, match_id, seq):
    return query(connect, "EXEC dbo.statsAtSeq @matchId = %s, @seq = %s", match_id, seq)


def expected(stream, seq, watermark):
    return reference(seq, outputs(stream, live=True), watermark)


def convert(connect):
    """One post-processor step (every lagging match to its watermark), on the test's post-processor connection."""
    if not hasattr(connect, "spadl"):
        connect.spadl = SpadlWorker(SpadlRepository(connect))
    return connect.spadl.step()


def actions(connect, match_id, upto=None):
    rows = query(connect, "SELECT * FROM dbo.spadlActions WHERE matchId = %s AND finalSeq <= %s ORDER BY actionId",
                 match_id, 2 ** 31 - 1 if upto is None else upto)
    bits = ("bodypartObserved", "fromShotOffTarget", "defensiveBlock")
    return [{c: (bool(r[c]) if c in bits else r[c]) for c in spadl.COLUMNS} for r in rows]


def whole(stream):
    return spadl.actions([m for m in stream if m.get("feed") == "MA3"],
                         next(c["id"] for c in stream[0]["contestant"] if c["position"] == "home"))


def test_stats_at_seq_equals_project_and_reference(connect):
    stream, clock = v2_stream.build(), Clock()
    match_id, final = stream[0]["matchId"], sum(m.get("type") == "MatchEvent" for m in stream)
    worker = StreamWorker(SqlRepository(connect), 60, clock=clock)
    worker.load()
    half = next(i for i, m in enumerate(stream) if m.get("seq") == 5000)
    feed(worker, stream[:half + 1])  # Event 5000 arrived; its MA3 rows have not.
    watermark = query(connect, "SELECT seq FROM dbo.matchWatermarks WHERE matchId = %s", match_id)[0]["seq"]
    assert watermark == 4999
    assert stats(connect, match_id, 4999) == []  # SPADL has not caught up: retry.
    assert convert(connect) == {match_id: len(outputs(stream[:half], live=True)["spadlActions"])}
    assert query(connect, "SELECT spadlSeq FROM dbo.matchWatermarks WHERE matchId = %s", match_id)[0]["spadlSeq"] == 4999
    assert stats(connect, match_id, 5000) == [] and stats(connect, "unknown-match", 1) == []
    assert stats(connect, match_id, 4999) == expected(stream, 4999, 4999)
    early = actions(connect, match_id)
    assert early == whole(stream)[:len(early)] and max(a["finalSeq"] for a in early) <= 4999
    feed(worker, stream[half + 1:], start=half + 1)
    settle(worker, clock)
    convert(connect)

    [mark] = query(connect, "SELECT * FROM dbo.matchWatermarks WHERE matchId = %s", match_id)
    assert (mark["seq"], mark["periodId"], mark["videoSeconds"]) == (final, 2, 5544.28)
    assert query(connect, "SELECT status FROM dbo.matches WHERE matchId = %s", match_id)[0]["status"] == "finished"
    assert actions(connect, match_id) == whole(stream)  # Incremental (two steps) equals whole-match.
    final_stats = stats(connect, match_id, final)
    assert len(final_stats) == 126 and final_stats == golden()["final"]
    by_id = {s["statId"]: s["value"] for s in final_stats}
    assert (by_id["chelsea:shots"], by_id["chelsea:shots_on_target"], by_id["chelsea:saves"], by_id["manutd:saves"],
            by_id["chelsea:passes"], by_id["manutd:passes"]) == (9, 3, 1, 3, 941, 462)
    assert (by_id["chelsea:shots_saved"], by_id["manutd:shots_saved"]) == (1, 2)
    assert (round(by_id["chelsea:possession"]), round(by_id["manutd:possession"])) == (64, 36)
    for seq in [0, 1, *range(611, final, 1100)]:  # 10 intermediate seqs plus the edges.
        assert stats(connect, match_id, seq) == expected(stream, seq, final), seq
        # Watermark-bounded reads: a snapshot sees exactly the actions final at its seq.
        assert actions(connect, match_id, seq) == [a for a in whole(stream) if a["finalSeq"] <= seq], seq
    assert stats(connect, match_id, final + 1) == []

    # VAR (no recording has one): United's goal (seq 1157) overturned, a United own goal (credited to Chelsea;
    # after Chelsea's goal at 8710) overturned, another goal confirmed.
    var = [var_row(match_id, 1, 2000, "manutd"), var_row(match_id, 2, 9000, "manutd", own_goal=True),
           var_row(match_id, 3, 10000, "chelsea", outcome="goal-confirmed")]
    for r in var:
        query(connect, f"INSERT dbo.rawEvents ({', '.join(r)}) VALUES ({', '.join(['%s'] * len(r))})", *r.values())
    rows = outputs(stream, live=True)
    rows["rawEvents"] += var
    for seq in (1999, 2000, 8999, 9000, final):
        assert stats(connect, match_id, seq) == reference(seq, rows, final), seq
    goals = lambda seq: tuple({s["statId"]: s["value"] for s in stats(connect, match_id, seq)}[f"{t}:goals"]
                              for t in ("chelsea", "manutd", "all"))
    assert (goals(1999), goals(2000), goals(8999), goals(final)) == ((0, 1, 1), (0, 0, 0), (1, 0, 1), (0, 0, 0))


def var_row(match_id, n, seq, team, own_goal=False, outcome="goal-overturned"):
    """A rawEvents row for an MA3 VAR decision (type 900, qualifier 901; 28 for an own goal)."""
    qualifier = [{"qualifierId": 901, "value": outcome}] + ([{"qualifierId": 28}] if own_goal else [])
    payload = {"feed": "MA3", "matchId": match_id, "id": 9_000_000 + n, "typeId": 900, "contestantId": team,
               "eventSeq": seq, "qualifier": qualifier}
    return {"matchId": match_id, "id": 9_000_000 + n, "seq": 90_000 + n, "eventId": 900 + n, "typeId": 900,
            "periodId": 2, "timeMin": 80, "timeSec": 0, "contestantId": team, "playerId": None, "outcome": 1,
            "x": None, "y": None, "eventTime": "2026-10-20 16:30:00", "payload": json.dumps(payload), "eventSeq": seq}


def test_purge_removes_every_row_and_stays_purged_after_restart(connect):
    stream, other, clock = v2_stream.build("0000aaaa"), v2_stream.build("0000bbbb"), Clock()
    match_id = stream[0]["matchId"]
    worker = StreamWorker(SqlRepository(connect), 60, clock=clock)
    worker.load()
    feed(worker, stream[:3000] + other[:3000])
    settle(worker, clock)
    convert(connect)
    spadl_seq = lambda: query(connect, "SELECT spadlSeq FROM dbo.matchWatermarks WHERE matchId = %s", match_id)[0]["spadlSeq"]
    reached = spadl_seq()
    # A stale replica (e.g. during a revision swap) never lowers spadlSeq.
    assert reached > 10 and SpadlRepository(connect).write(match_id, [], 10) and spadl_seq() == reached
    ids, counts = worker.purge(match_id, SqlRepository(connect))
    assert ids == [match_id] and counts["canonicalEvents"] > 0 and counts["possessionSamples"] > 0
    assert counts["spadlActions"] > 0 and counts["spadlProgress"] == 1

    def rows_for(m):
        found = {t: query(connect, f"SELECT COUNT(*) AS n FROM dbo.{t} WHERE matchId = %s", m)[0]["n"]
                 for t in (*MATCH_TABLES, "matchWatermarks")}
        found["outbox"] = query(connect, "SELECT COUNT(*) AS n FROM dbo.localStreamOutbox "
                                         "WHERE JSON_VALUE(body, '$.matchId') = %s", m)[0]["n"]
        return found

    assert set(rows_for(match_id).values()) == {0}
    restarted = StreamWorker(SqlRepository(connect), 60, clock=clock)  # New process.
    restarted.load()
    feed(restarted, stream[:4000], start=10_000)  # Redelivery, MA1 included.
    settle(restarted, clock)
    convert(connect)
    assert set(rows_for(match_id).values()) == {0} and stats(connect, match_id, 0) == []
    stale = SpadlRepository(connect)  # A post-processor step that read before the purge writes nothing.
    assert stale.write(match_id, whole(stream)[:5], 100) is False and set(rows_for(match_id).values()) == {0}
    assert all(rows_for(other[0]["matchId"])[t] for t in ("matches", "canonicalEvents", "possessionSamples"))

    ids, counts = restarted.purge(None, SqlRepository(connect))  # Purge all: tombstones plus a cut-off.
    assert ids == [other[0]["matchId"]] and set(rows_for(other[0]["matchId"]).values()) == {0}
    assert query(connect, "SELECT COUNT(*) AS n FROM dbo.statDefinitions")[0]["n"] == 42  # Configuration stays.
    assert query(connect, "SELECT COUNT(*) AS n FROM dbo.trendDefinitions")[0]["n"] == len(trends.definitions())
    assert {r["matchId"] for r in query(connect, "SELECT matchId FROM dbo.purgedMatches")} == {match_id, other[0]["matchId"]}
    assert query(connect, "SELECT cutoffAt FROM dbo.purgeCutoff")


def test_interleaved_matches_stay_isolated(connect):
    a, clock = v2_stream.build("1111aaaa"), Clock()
    b = v2_stream.build("2222bbbb", kickoff=v2_stream.KICKOFF + timedelta(seconds=11.7))
    cut = lambda s: s[:next(i for i, m in enumerate(s) if m.get("seq") == 3000)]
    worker = StreamWorker(SqlRepository(connect), 60, clock=clock)
    worker.load()
    feed(worker, v2_stream.interleave(cut(a), cut(b)), batch=173)
    settle(worker, clock)
    assert set(convert(connect)) == {a[0]["matchId"], b[0]["matchId"]}
    for stream in (a, b):
        match_id = stream[0]["matchId"]
        assert query(connect, "SELECT seq FROM dbo.matchWatermarks WHERE matchId = %s", match_id)[0]["seq"] == 2999
        for seq in (1, 1500, 2999):
            assert stats(connect, match_id, seq) == expected(cut(stream), seq, 2999), (match_id, seq)
    teams = query(connect, "SELECT matchId, COUNT(*) AS n FROM dbo.matchTeams GROUP BY matchId")
    assert sorted((t["matchId"], t["n"]) for t in teams) == [(a[0]["matchId"], 2), (b[0]["matchId"], 2)]
