"""Narrative GraphQL API, served in-process over a fake-agent run of the synthetic match."""
import asyncio
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from narrative_engine.agents.fake import FakeAgents
from narrative_engine.api import NarrativeApi, schema
from narrative_engine.match_data.fixture import FixtureMatchData
from narrative_engine.core.models import USER_TYPES, MinuteClosed, PresenceChanged
from narrative_engine.core.orchestrator import MatchOrchestrator, utcnow
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import JsonlSink, read_narratives, read_notifications

FIXTURES = Path(__file__).parent / "fixtures"
NOTIFICATIONS = FIXTURES / "itg-syn-0001-notifications.jsonl"
MATCH = "itg-syn-0001-local"
PAGE = """query ($m: String!, $u: String!, $after: Int, $first: Int) {
  narratives(matchId: $m, userType: $u, afterSeq: $after, first: $first) {
    items { id seq stepId triggerType triggerReason matchTime { periodId timeMin label } text promptVersion }
    hasNextPage endCursor } }"""
STATE = "query ($m: String!) { matchState(matchId: $m) { status lastSummarised { label } activeUserTypes } }"


def replay(store, messages, clock):
    engine = MatchOrchestrator(MATCH, FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS), FakeAgents(),
                               store, JsonlSink(clock["out"]), now=lambda: clock["now"])

    async def go():
        for m in messages:
            await engine.handle(m)
    asyncio.run(go())


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    clock = {"now": utcnow(), "out": tmp_path_factory.mktemp("run") / "narratives.jsonl"}
    store = MemoryStore()
    messages = [m for _, m in read_notifications(NOTIFICATIONS) if m]
    replay(store, messages, clock)
    return store, clock


def query(store, document, now=utcnow, **variables):
    async def post():
        transport = httpx.ASGITransport(app=NarrativeApi(store, now=now))
        async with httpx.AsyncClient(transport=transport, base_url="http://engine") as client:
            return (await client.post("/graphql", json={"query": document, "variables": variables})).json()
    return asyncio.run(post())


def test_pages_through_a_bucket_backlog_like_a_reconnecting_client(run):
    store, _ = run
    expected = asyncio.run(store.narratives(MATCH, "away:casual"))
    seen, after = [], 0
    while True:
        page = query(store, PAGE, m=MATCH, u="away:casual", after=after, first=5)["data"]["narratives"]
        seen += page["items"]
        if not page["hasNextPage"]:
            break
        after = page["endCursor"]
    assert [n["seq"] for n in seen] == [n.seq for n in expected] == list(range(1, len(expected) + 1))
    assert [n["text"] for n in seen] == [n.text for n in expected]
    goal = next(n for n in seen if n["triggerType"] == "keyEvent")
    assert goal["matchTime"] == {"periodId": 1, "timeMin": 23, "label": "24'"} and "Mensah" in goal["triggerReason"]
    assert seen[-1]["triggerType"] == "fullTime" and seen[-1]["matchTime"]["label"] == "90+6'"


def test_after_the_latest_seq_is_empty_and_step_ids_link_buckets(run):
    store, _ = run
    page = query(store, PAGE, m=MATCH, u="home:simple", after=999)["data"]["narratives"]
    assert page == {"items": [], "hasNextPage": False, "endCursor": None}
    first = {u: query(store, PAGE, m=MATCH, u=u, first=1)["data"]["narratives"]["items"][0] for u in USER_TYPES}
    assert len({n["stepId"] for n in first.values()}) == 1 and len({n["id"] for n in first.values()}) == 12


def test_bad_arguments_are_graphql_errors(run):
    store, _ = run
    body = query(store, PAGE, m=MATCH, u="home:expert")
    assert body["data"] is None and "userType must be one of" in body["errors"][0]["message"]
    assert "between 1 and 200" in query(store, PAGE, m=MATCH, u="home:simple", first=500)["errors"][0]["message"]
    assert query(store, "mutation { x }")["errors"]  # read-only: no mutations in the schema
    assert "type Mutation" not in schema.as_str()


def test_match_state_follows_presence_and_its_staleness(tmp_path):
    store, clock = MemoryStore(), {"now": utcnow(), "out": tmp_path / "narratives.jsonl"}
    assert query(store, STATE, m=MATCH)["data"]["matchState"] is None
    messages = [m for _, m in read_notifications(NOTIFICATIONS) if m][:20]
    replay(store, [PresenceChanged(MATCH, {"home:casual": 2}, clock["now"])] + messages, clock)
    state = query(store, STATE, now=lambda: clock["now"], m=MATCH)["data"]["matchState"]
    assert state["status"] == "live" and state["activeUserTypes"] == ["home:casual"]
    assert state["lastSummarised"]["label"] == [m for m in messages if isinstance(m, MinuteClosed)][-1].clock.label
    later = clock["now"] + timedelta(minutes=5)
    assert query(store, STATE, now=lambda: later, m=MATCH)["data"]["matchState"]["activeUserTypes"] == list(USER_TYPES)


def test_full_run_state_and_jsonl_round_trip(run):
    store, clock = run
    state = query(store, STATE, m=MATCH)["data"]["matchState"]
    assert state["status"] == "complete" and state["lastSummarised"]["label"] == "90+6'"
    reloaded = MemoryStore()
    for n in read_narratives(clock["out"]):
        asyncio.run(reloaded.add_narrative(n))
    assert query(reloaded, PAGE, m=MATCH, u="neutral:analyst") == query(store, PAGE, m=MATCH, u="neutral:analyst")
