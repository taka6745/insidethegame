"""Read-only checks against the real local DAB (etl: `python -m devtools local-up` + `load-local`).

Skipped unless ETL_GRAPHQL_URL (default http://localhost:5000/graphql) answers and holds a
load of the synthetic match itg-syn-0001. Never writes to the ETL.
"""
import asyncio
import os
from pathlib import Path

import httpx
import pytest

from narrative_engine.agents.fake import FakeAgents
from narrative_engine.match_data.etl_graphql import GraphQLMatchData
from narrative_engine.match_data.fixture import FixtureMatchData
from narrative_engine.core.models import KeyEventDetected, MatchClock
from narrative_engine.core.orchestrator import MatchOrchestrator
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink, read_notifications

URL = os.environ.get("ETL_GRAPHQL_URL", "http://localhost:5000/graphql")
FIXTURES = Path(__file__).parent / "fixtures"
NOTIFICATIONS = FIXTURES / "itg-syn-0001-notifications.jsonl"
FIXTURE = FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS)


def loaded_match():
    """A match in the local DB whose events are the fixture's, or skip."""
    query = "{ matches { items { matchId description } } }"
    try:
        body = httpx.post(URL, json={"query": query}, timeout=5).json()
    except (httpx.HTTPError, ValueError):
        pytest.skip(f"local DAB not reachable at {URL}")
    for m in body.get("data", {}).get("matches", {}).get("items", []):
        if (m["description"] or "").startswith("Riverside FC v Harbour Athletic"):
            data = GraphQLMatchData(URL)
            events = asyncio.run(data.events(m["matchId"], MatchClock(1, 0), MatchClock(2, 99)))
            if [e["id"] for e in events] == [e["id"] for e in sorted(FIXTURE.raw, key=lambda e: e["seq"])]:
                return m["matchId"]
    pytest.skip("no complete load of itg-syn-0001 in the local DB")


@pytest.fixture(scope="module")
def match_id():
    return loaded_match()


def test_live_reads_match_the_fixture(match_id):
    async def check():
        data = GraphQLMatchData(URL)
        info = await data.match_info(match_id)
        assert (info.home.name, info.away.name) == (FIXTURE.info.home.name, FIXTURE.info.away.name)
        window = (MatchClock(1, 46), MatchClock(2, 46), 30)
        assert [e["id"] for e in await data.events(match_id, *window)] == \
               [e["id"] for e in await FIXTURE.events(match_id, *window)]
        live_keys = await data.key_events(match_id, MatchClock(2, 53), 34)
        assert sorted(k["id"] for k in live_keys) == sorted(k["id"] for k in await FIXTURE.key_events(
            match_id, MatchClock(2, 53), 34))
        assert await data.period_end(match_id, 1) == await FIXTURE.period_end(match_id, 1)
        assert await data.period_end(match_id, 2) == await FIXTURE.period_end(match_id, 2)
        assert (await data.raw_event(match_id, "c-har", 405))["typeId"] == 16
        rows = await data.stats_as_of(match_id, MatchClock(1, 38))  # quiet minute: falls back to 37
        assert {r["minuteLabel"] for r in rows} == {"38'"} and {r["position"] for r in rows} == {"home", "away"}
        await data.aclose()
    asyncio.run(check())


def test_live_author_context_stops_at_the_trigger(match_id):
    messages = [m for _, m in read_notifications(NOTIFICATIONS, match_id) if m]
    first_goal = next(i for i, m in enumerate(messages) if isinstance(m, KeyEventDetected))
    agents, store = FakeAgents(), MemoryStore()

    async def go():
        data = GraphQLMatchData(URL)
        engine = MatchOrchestrator(match_id, data, agents, store, MemorySink(store))
        for m in messages[:first_goal + 1]:
            await engine.handle(m)
        await data.aclose()
    asyncio.run(go())
    call = next(v for a, v in agents.calls if a == "author" and v["trigger_reason"].startswith("Key event"))
    assert call["key_event_ledger"].count("\n") == 0 and "Mensah" in call["key_event_ledger"]
    assert "As of 23'" in call["game_state_statistics"] and "Score: Riverside FC (home) 0 - 0" in \
        call["game_state_statistics"]
    times = [l.split()[0] for l in call["match_events"].splitlines() if l.startswith("  ") and l.strip()[0].isdigit()]
    assert max(times) == "23:09"
