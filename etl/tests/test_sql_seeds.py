"""SQL Server: demo seeds (PLAN.md §10.6) through SqlSeeds, the admin routes' code path, on a real database.

A run held at a seq is exported, sent as JSON, purged and restored under a new matchId; the restored rows equal
the recorded ones, the run then carries on from the seed to the same rows as a run held there and never
exported, and a purge removes it. Needs a disposable SQL Server (sql_server.py):
    ETL_TEST_SQL_PASSWORD=… [ETL_TEST_SQL_HOST=127.0.0.1 ETL_TEST_SQL_PORT=1433] pytest tests/test_sql_seeds.py
"""
import json

import pytest

import sql_server
import v2_stream
from local_stream import demo_seeds
from local_stream.repository import MATCH_TABLES, SqlRepository
from local_stream.worker import StreamWorker
from sql_server import query
from test_sql_catalogue import SCRIPTS, Clock, convert, feed, settle, stats

pytestmark = sql_server.enabled
SEQ = 1500  # the hold point: events up to SEQ were sent


@pytest.fixture
def connect():
    yield from sql_server.database("itg_seeds", SCRIPTS)


def held(stream):
    """What a run held after SEQ sent: everything before the first message of SEQ + 1."""
    return next(i for i, m in enumerate(stream) if m.get("seq") == SEQ + 1)


def rows(connect, match_id, run_id):
    """Every row of a match, ids normalised, without the ingestion time."""
    found = {}
    for table in MATCH_TABLES:
        part = [{k: v for k, v in r.items() if k != "ingestedAt"}
                for r in query(connect, f"SELECT * FROM dbo.{table} WHERE matchId = %s", match_id)]
        text = json.dumps(part, default=str).replace(match_id, "M").replace(run_id, "R")
        found[table] = sorted(json.dumps(r, sort_keys=True) for r in json.loads(text))
    return found


def test_a_seed_round_trips_through_sql_and_the_run_carries_on(connect):
    source, new, reference = (v2_stream.build(run) for run in ("0000aaaa", "0000cccc", "0000dddd"))
    ids = [(s[0]["matchId"], s[0]["runId"]) for s in (source, new, reference)]
    (source_id, source_run), (new_id, new_run), (ref_id, ref_run) = ids
    clock = Clock()
    repository = SqlRepository(connect)
    worker = StreamWorker(repository, 60, clock=clock)
    worker.load()
    seeds = demo_seeds.SqlSeeds(repository)
    cut = held(source)
    feed(worker, source[:cut])
    settle(worker, clock)
    convert(connect)

    schema, tables = demo_seeds.export(worker, seeds, source_id)
    assert schema == seeds.schema() and len(tables["canonicalEvents"]) == SEQ
    assert max(r["seq"] for r in tables["canonicalEvents"]) == SEQ and tables["spadlActions"]
    recorded = rows(connect, source_id, source_run)
    seed = json.loads(json.dumps(tables).replace(source_id, new_id).replace(source_run, new_run))  # over HTTP
    worker.purge(source_id, repository)  # the recording leaves every owner once captured

    refused = (("past seq", seed, SEQ - 1, schema, new_id), ("another schema", seed, SEQ, "other", new_id),
               ("tombstoned", tables, SEQ, schema, source_id),
               ("another match", {**seed, "matches": tables["matches"]}, SEQ, schema, new_id))
    for why, body, max_seq, fingerprint, match_id in refused:
        with pytest.raises(demo_seeds.RestoreRefused):
            demo_seeds.restore(worker, seeds, match_id, body, max_seq, fingerprint)
        assert not query(connect, "SELECT 1 AS x FROM dbo.canonicalEvents WHERE matchId = %s", new_id), why
    counts = demo_seeds.restore(worker, seeds, new_id, seed, SEQ, schema)
    assert counts["canonicalEvents"] == SEQ and new_id in worker.matches
    assert rows(connect, new_id, new_run) == recorded  # the restored state is the recorded state
    with pytest.raises(demo_seeds.RestoreRefused):
        demo_seeds.restore(worker, seeds, new_id, seed, SEQ, schema)  # known now

    feed(worker, new[held(new):], start=50_000)  # the released run: what follows the seed, no MA1
    settle(worker, clock)
    convert(connect)
    # The same run never exported: held at the point (its idle stream closes the open minute window), then on.
    feed(worker, reference[:cut], start=100_000)
    settle(worker, clock)
    convert(connect)
    feed(worker, reference[cut:], start=150_000)
    settle(worker, clock)
    convert(connect)
    final = sum(m.get("type") == "MatchEvent" for m in reference)
    assert rows(connect, new_id, new_run) == rows(connect, ref_id, ref_run)
    assert stats(connect, new_id, final) == [{**r, "matchId": new_id} if "matchId" in r else r
                                             for r in stats(connect, ref_id, final)]

    worker.purge(new_id, repository)
    assert not any(rows(connect, new_id, new_run).values())
