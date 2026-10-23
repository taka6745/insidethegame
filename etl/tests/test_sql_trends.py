"""SQL Server: trendMinutesAtSeq, trendsAtSeq and trendSpellsAtSeq (migrations 011, 014, 015) equal reference/trends.py
on all three recordings at 10 seqs each, are empty above spadlSeq, read their thresholds from trendDefinitions and
their formula constants from trendParameters, and
stay fast at full time. Expected values come from the recordings via the reference, so a re-rendered recording
needs no edit here. Same disposable server as test_sql_catalogue:
    ETL_TEST_SQL_PASSWORD=… [ETL_TEST_SQL_HOST=127.0.0.1 ETL_TEST_SQL_PORT=1433] pytest tests/test_sql_trends.py
"""
import json
import math
import time
from pathlib import Path

import pytest

import sql_server
import v2_stream
from reference import trends
from spadl.worker import SpadlRepository
from sql_server import query
from local_stream.repository import sql_value
from support import outputs, var_row

pytestmark = sql_server.enabled
ETL = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ETL / "sql" / "migrations").glob("*.sql"))
PROCS = {"trendMinutesAtSeq": trends.trend_minutes_at_seq, "trendsAtSeq": trends.trends_at_seq,
         "trendSpellsAtSeq": trends.spells_at_seq}


def insert_rows(connect, rows, batch=500):
    """ETL's stored rows for one match, as the stream writes them."""
    conn = connect.shared
    for table in ("matches", "matchTeams", "canonicalEvents", "possessionSamples", "rawEvents"):
        columns = list(rows[table][0])
        for i in range(0, len(rows[table]), batch):
            chunk = rows[table][i:i + batch]
            values = ", ".join(["(" + ", ".join(["%s"] * len(columns)) + ")"] * len(chunk))
            conn.cursor().execute(f"INSERT dbo.{table} ({', '.join(columns)}) VALUES {values}",
                                  tuple(sql_value(c, r[c]) for r in chunk for c in columns))
    conn.commit()


@pytest.fixture(scope="module")
def loaded():
    """One database with the three recordings stored whole (as ETL stores them) and their SPADL actions."""
    for connect in sql_server.database("itg_trends", SCRIPTS):
        runs = {}
        for fixture in v2_stream.FIXTURES:
            rows = outputs(v2_stream.build(fixture=fixture))
            match_id, final = rows["matches"][0]["matchId"], len(rows["canonicalEvents"])
            insert_rows(connect, rows)
            query(connect, "INSERT dbo.matchProgress (matchId, seq) VALUES (%s, %s)", match_id, final)
            assert SpadlRepository(connect).write(match_id, rows["spadlActions"], final)
            runs[fixture] = (match_id, final, rows)
        yield connect, runs


def expected(proc, rows, seq, watermark, defs=None, params=None):
    return PROCS[proc](rows["matches"][0], rows["canonicalEvents"], rows["possessionSamples"], seq, watermark, defs,
                       actions=rows["spadlActions"], raw=rows["rawEvents"], params=params)


def run(connect, proc, match_id, seq):
    return query(connect, f"EXEC dbo.{proc} @matchId = %s, @seq = %s", match_id, seq)


def same(got, want):
    """Rows equal; floats to 1e-9 (SQL Server sums in its own order)."""
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert list(g) == list(w), (list(g), list(w))
        for k in w:
            a, b = g[k], w[k]
            if isinstance(b, float) or isinstance(a, float):
                assert a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), (k, g, w)
            else:
                assert a == b, (k, g, w)


@pytest.mark.parametrize("fixture", v2_stream.FIXTURES)
def test_procedures_equal_the_reference_at_ten_seqs(loaded, fixture):
    connect, runs = loaded
    match_id, final, rows = runs[fixture]
    half_time = max(e["seq"] for e in rows["canonicalEvents"] if e["periodId"] == 1)
    seqs = sorted({1, 400, *range(900, final, final // 7), half_time, half_time + 1, final})[:10]
    for seq in seqs:
        for proc in PROCS:
            same(run(connect, proc, match_id, seq), expected(proc, rows, seq, final))
    flagged = [r for r in run(connect, "trendsAtSeq", match_id, final) if r["flagged"]]
    assert flagged and all(r["enabled"] for r in flagged)


def test_empty_outside_the_snapshot_bounds(loaded):
    connect, runs = loaded
    match_id, final, rows = runs["riverton-forgeham"]
    mid = final // 2
    query(connect, "UPDATE dbo.spadlProgress SET seq = %s WHERE matchId = %s", mid, match_id)  # SPADL lags.
    try:
        for proc in PROCS:
            assert run(connect, proc, match_id, mid + 1) == [] and run(connect, proc, match_id, -1) == []
            assert run(connect, proc, "unknown-match", 1) == []
            same(run(connect, proc, match_id, mid), expected(proc, rows, mid, mid))
    finally:
        query(connect, "UPDATE dbo.spadlProgress SET seq = %s WHERE matchId = %s", final, match_id)
    assert run(connect, "trendsAtSeq", match_id, final + 1) == []  # Above the watermark.


def test_definitions_are_the_seed_and_reseeding_changes_flags(loaded):
    connect, runs = loaded
    stored = query(connect, "SELECT * FROM dbo.trendDefinitions ORDER BY displayOrder")
    seed = trends.definitions()
    assert [{k: r[k] for k in seed[0]} for r in stored] == [{**d, "enabled": bool(d["enabled"])} for d in seed]
    match_id, final, rows = runs["skybridge-whitmore"]
    # ppda flags its low end: a very high bar makes every value "high"; momentum and fast breaks come on too.
    reseed = [{**d, "enabled": True, "highAt": 1e6 if d["trendId"] == "ppda" else d["highAt"]} for d in seed]
    block = json.dumps([{k: v for k, v in d.items() if k != "displayOrder"} for d in reseed])
    query(connect, "EXEC dbo.seedTrendDefinitions %s", block)
    try:
        for proc in PROCS:
            same(run(connect, proc, match_id, final), expected(proc, rows, final, final, reseed))
        assert any(r["trendId"] == "ppda" and r["level"] == "high" for r in run(connect, "trendsAtSeq", match_id, final))
    finally:
        query(connect, "EXEC dbo.seedTrendDefinitions %s",
              json.dumps([{k: v for k, v in d.items() if k != "displayOrder"} for d in seed]))
    assert query(connect, "SELECT COUNT(*) AS n FROM dbo.trendDefinitions")[0]["n"] == len(seed)


def test_formula_parameters_are_the_seed_and_reseeding_changes_the_values(loaded):
    connect, runs = loaded
    seed = trends.parameters()
    stored = {r["name"]: r["value"] for r in query(connect, "SELECT name, value FROM dbo.trendParameters")}
    assert stored == seed
    match_id, final, rows = runs["riverton-forgeham"]
    rows_of = lambda: query(connect, "SELECT name, value, meaning FROM dbo.trendParameters")
    original = json.dumps([dict(r) for r in rows_of()])
    changed = {**seed, "long_pass_metres": 20.0, "momentum_alpha": 0.7, "flank_lanes": 4.0, "threat_shot": 5.0,
               "build_line_metres": 50.0, "ball_gap_cap_seconds": 5.0, "fast_break_seconds": 20.0}
    query(connect, "EXEC dbo.seedTrendParameters %s",
          json.dumps([{"name": k, "value": v, "meaning": "test"} for k, v in changed.items()]))
    try:
        for proc in PROCS:
            got = run(connect, proc, match_id, final)
            same(got, expected(proc, rows, final, final, params=changed))
            assert proc == "trendSpellsAtSeq" or got != expected(proc, rows, final, final)
    finally:
        query(connect, "EXEC dbo.seedTrendParameters %s", original)
    assert {r["name"]: r["value"] for r in rows_of()} == seed


@pytest.mark.parametrize("change", ["missing", "unknown", "null"])
def test_a_parameter_block_without_every_name_is_refused_and_changes_nothing(loaded, change):
    """Migration 016: trendMinuteRows reads 13 names; a block that drops, misspells or nulls one is refused."""
    connect, _ = loaded
    block = [{"name": k, "value": v, "meaning": "test"} for k, v in trends.parameters().items()]
    if change == "missing":
        block = block[1:]
    elif change == "unknown":
        block[0] = {**block[0], "name": block[0]["name"] + "_typo"}
    else:
        block[0] = {**block[0], "value": None}
    before = query(connect, "SELECT name, value, meaning FROM dbo.trendParameters ORDER BY name")
    with pytest.raises(Exception, match="trendParameters not changed"):
        query(connect, "EXEC dbo.seedTrendParameters %s", json.dumps(block))
    connect.shared.rollback()
    assert query(connect, "SELECT name, value, meaning FROM dbo.trendParameters ORDER BY name") == before


def test_var_overturns_change_the_game_state_as_the_reference(loaded):
    """No recording has VAR: City's goal (69') overturned at 80', then City's own goal (47', Whitmore') at 85'."""
    connect, runs = loaded
    match_id, final, rows = runs["skybridge-whitmore"]
    first = lambda minute: min(e["seq"] for e in rows["canonicalEvents"]
                               if e["periodId"] == 2 and e["matchTimeSeconds"] // 60 == minute)
    var = [{**var_row(match_id, 1, first(80), "skybridge"), "timeMin": 80},
           {**var_row(match_id, 2, first(85), "skybridge", own_goal=True), "timeMin": 85}]
    for r in var:
        query(connect, f"INSERT dbo.rawEvents ({', '.join(r)}) VALUES ({', '.join(['%s'] * len(r))})", *r.values())
    with_var = {**rows, "rawEvents": rows["rawEvents"] + var}
    try:
        for seq in (first(85) - 1, final):
            for proc in PROCS:
                same(run(connect, proc, match_id, seq), expected(proc, with_var, seq, final))
        lead = lambda seq: run(connect, "trendMinutesAtSeq", match_id, seq)[-2]["leadAtStart"]  # City, last minute
        assert (lead(first(85) - 1), lead(final)) == (-1, 0)
    finally:
        query(connect, "DELETE dbo.rawEvents WHERE matchId = %s AND typeId = 900", match_id)


def test_full_time_calls_are_fast(loaded):
    connect, runs = loaded
    match_id, final, _ = runs["riverton-forgeham"]
    for proc in PROCS:
        run(connect, proc, match_id, final)  # Warm the plan cache.
        took = []
        for _ in range(3):
            start = time.perf_counter()
            run(connect, proc, match_id, final)
            took.append(time.perf_counter() - start)
        print(f"{proc}: {1000 * min(took):.0f} ms")
        assert min(took) < 0.5, (proc, took)  # Target 200 ms; emulated servers are slower.
