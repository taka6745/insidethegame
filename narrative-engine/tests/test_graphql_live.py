"""Read-only checks of the GraphQL client against the real ETL GraphQL of the shared stack (`./dev up backend`).

Targets a feed run of the Riverton Rovers–United recording (`./dev demo start riverton-forgeham`, matchId
riverton-forgeham-{run}); skipped unless ETL_GRAPHQL_URL (default http://localhost:15001/graphql) answers and
holds one past seq 500. Up to the run's watermark, the live reads must equal the recording's test data
(tests/riverton_forgeham.py): MA3 rows, key events, SPADL actions and the catalogue's golden values. Never writes.
"""
import asyncio
import os

import httpx
import pytest

import riverton_forgeham
from narrative_engine.devtools.fake_agents import FakeAgents
from narrative_engine.context.render import ACTION_FIELDS
from narrative_engine.core.models import MatchClock, parse_notification
from narrative_engine.core.orchestrator import MatchOrchestrator
from narrative_engine.devtools.targets import StaticTargets, default_targets
from narrative_engine.match_data.etl_graphql import GraphQLMatchData
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink

URL = os.environ.get("ETL_GRAPHQL_URL", "http://localhost:15001/graphql")
FIXTURE = riverton_forgeham.data(stats=riverton_forgeham.golden_stats())
FIELDS = ACTION_FIELDS.split()


def feed_run():
    """(matchId, snapshot seq) of the most advanced Riverton Rovers–United feed run, or skip."""
    query = ("{ matches(filter: {fixture: {eq: \"riverton-forgeham\"}}) { items { matchId } } "
             "matchWatermarks { items { matchId seq spadlSeq } } }")
    try:
        data = httpx.post(URL, json={"query": query}, timeout=5).json()["data"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pytest.skip(f"ETL GraphQL not reachable at {URL}")
    runs = {m["matchId"] for m in data["matches"]["items"]}
    marks = [(min(w["seq"], w["spadlSeq"] or 0), w["matchId"]) for w in data["matchWatermarks"]["items"]
             if w["matchId"] in runs]
    seq, match_id = max(marks, default=(0, None))
    if seq < 500:
        pytest.skip("no Riverton Rovers–United feed run past seq 500 in the ETL")
    return match_id, seq


@pytest.fixture(scope="module")
def run():
    return feed_run()


def clock_at(seq):
    """Match clock of the latest MA3 row at or before canonical seq `seq`."""
    row = max((e for e in FIXTURE.raw if e["eventSeq"] <= seq), key=lambda e: e["eventSeq"])
    return MatchClock(row["periodId"], row["timeMin"]), row["timeSec"]


def test_live_reads_equal_the_recording(run):
    match_id, seq = run
    clock, second = clock_at(seq)

    async def check():
        data = GraphQLMatchData(URL)
        info = await data.match_info(match_id)
        assert (info.home.name, info.away.name) == (FIXTURE.info.home.name, FIXTURE.info.away.name)
        window = (MatchClock(1, 0), clock, second)
        live = [e for e in await data.events(match_id, *window) if e["eventSeq"] <= seq]
        assert [e["id"] for e in live] == [e["id"] for e in await FIXTURE.events(match_id, *window) if e["eventSeq"] <= seq]
        assert sorted(k["id"] for k in await data.key_events(match_id, clock, second)) == \
               sorted(k["id"] for k in await FIXTURE.key_events(match_id, clock, second))
        # SQL float round trips differ in the last bits (28.01600000000001 vs 28.016000000000005).
        fields = lambda a: {f: round(a[f], 6) if isinstance(a[f], float) else a[f] for f in FIELDS}
        expected = [fields(a) for a in await FIXTURE.actions(match_id, 0, seq)]
        assert [fields(a) for a in await data.actions(match_id, 0, seq)] == expected
        for s in [s for s in sorted(FIXTURE.stats) if 0 < s <= seq][-3:]:  # golden seqs reached by the run
            got = {r["statId"]: (r["value"], r["available"]) for r in await data.stats_at(match_id, s)}
            assert got == {r["statId"]: (r["value"], r["available"]) for r in await FIXTURE.stats_at(match_id, s)}, s
        assert await data.event_seq(match_id, clock, second) == await FIXTURE.event_seq(match_id, clock, second)
        await data.aclose()
    asyncio.run(check())


def test_live_author_context_stops_at_the_trigger(run):
    match_id, seq = run
    timeline = riverton_forgeham.timeline()
    first_goal = next(i for i, (body, _) in enumerate(timeline)
                      if body["messageType"] == "KeyEventDetected" and body["keyType"] == "Goal")
    if timeline[first_goal][1] > seq:
        pytest.skip("the run has not reached the first goal")
    agents, store = FakeAgents(), MemoryStore()

    async def go():
        data = GraphQLMatchData(URL)
        engine = MatchOrchestrator(match_id, data, agents, store, MemorySink(store),
                                   targets=StaticTargets(default_targets()))
        for body, _ in timeline[:first_goal + 1]:
            await engine.handle(parse_notification({**body, "matchId": match_id}))
        await data.aclose()
    asyncio.run(go())
    call = next(v for a, v in agents.calls if a == "author" and v["trigger_reason"].startswith("Key event")
                and "Goal for" in v["trigger_reason"])
    # The penalty award (09:31) and Brightwell's penalty (09:35).
    assert call["key_event_ledger"].count("\n") == 1 and "Brightwell" in call["key_event_ledger"]
    assert "key event: Goal for Forgeham United" in call["match_events"]
    times = [line.split()[0] for line in call["match_events"].splitlines()
             if line.startswith("  ") and line.strip()[0].isdigit()]
    assert max(times, key=lambda t: tuple(map(int, t.split(":")))) == "09:35"  # nothing after the goal
