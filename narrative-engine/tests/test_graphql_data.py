"""GraphQL client against an in-process fake of Data API builder.

The fake evaluates the client's filter variables (eq/gt/gte/lt/lte, and/or), orderBy and
cursor pagination over rows built from the synthetic match itg-syn-0001 (not real data).
test_graphql_live.py runs the same client against the real local DAB when it is up.
"""
import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest

from narrative_engine.agents.fake import FakeAgents
from narrative_engine.match_data.etl_graphql import GraphQLError, GraphQLMatchData
from narrative_engine.match_data.fixture import FixtureMatchData
from narrative_engine.core.models import MatchClock
from narrative_engine.core.orchestrator import MatchOrchestrator
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink, read_notifications

FIXTURES = Path(__file__).parent / "fixtures"
MATCH = "itg-syn-0001-local"
NOTIFICATIONS = FIXTURES / "itg-syn-0001-notifications.jsonl"
FIXTURE = FixtureMatchData(FIXTURES / "itg-syn-0001.jsonl", NOTIFICATIONS)
ENTITY_TYPES = {"matches": "Match", "rawEvents": "RawEvent", "keyEvents": "KeyEvent",
                "matchStatsAsOfs": "MatchStatsAsOf"}  # singular names from etl/dab/dab-config.json
OPS = {"eq": lambda a, b: a == b, "neq": lambda a, b: a != b, "gt": lambda a, b: a > b,
       "gte": lambda a, b: a >= b, "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b}


def stat_row(position, period, minute, goals=0):
    return {"matchId": MATCH, "contestantId": f"c-{position}", "position": position, "periodId": period,
            "timeMin": minute, "minuteLabel": MatchClock(period, minute).label, "goals": goals, "ownGoals": 0,
            "passes": 10, "passesCompleted": 9, "shots": 1, "shotsOnTarget": 0, "corners": 0, "fouls": 0,
            "yellowCards": 0, "redCards": 0, "events": 12, "possessionPct": 50.0}


def matches_filter(row, f):
    if "and" in f:
        return all(matches_filter(row, c) for c in f["and"])
    if "or" in f:
        return any(matches_filter(row, c) for c in f["or"])
    (column, ops), = f.items()
    return all(OPS[op](row[column], value) for op, value in ops.items())


class FakeDab:
    page_cap = 50

    def __init__(self):
        with open(FIXTURES / "itg-syn-0001.jsonl") as f:
            ma1 = {**json.loads(f.readline()), "matchId": MATCH}
        self.tables = {
            "matches": [{"matchId": MATCH, "payload": json.dumps(ma1)}],
            "rawEvents": [{**{k: e[k] for k in ("id", "seq", "eventId", "typeId", "periodId", "timeMin", "timeSec",
                                                "contestantId")}, "matchId": MATCH, "payload": json.dumps(e)}
                          for e in FIXTURE.raw],
            "keyEvents": [{**k, "matchId": MATCH} for k in FIXTURE.keys],
            "matchStatsAsOfs": [stat_row(p, 1, m, goals=int(m >= 23 and p == "home"))
                                for m in (20, 22, 23) for p in ("home", "away")],
        }
        self.requests, self.hidden_stats = [], set()  # hidden: clocks whose rows are "not written yet"

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        query, variables = body["query"], body["variables"]
        if "bogus" in query:
            return httpx.Response(400, json={"errors": [{"message": "unknown field bogus"}]})
        entity = re.search(r"\{ (\w+)\(filter", query).group(1)
        assert f"$f: {ENTITY_TYPES[entity]}FilterInput" in query
        rows = [r for r in self.tables[entity] if matches_filter(r, variables["f"])]
        if entity == "matchStatsAsOfs":
            rows = [r for r in rows if MatchClock(r["periodId"], r["timeMin"]) not in self.hidden_stats]
        if order := re.search(r"orderBy: \{(.*?)\}", query):
            for column, direction in reversed([part.split(": ") for part in order.group(1).split(", ")]):
                rows.sort(key=lambda r: r[column], reverse=direction == "DESC")
        start = int(variables["after"] or 0)
        size = min(variables["first"], self.page_cap)
        page = rows[start:start + size]
        more = start + size < len(rows)
        return httpx.Response(200, json={"data": {entity: {"items": page, "hasNextPage": more,
                                                           "endCursor": str(start + size) if more else None}}})


def client(dab):
    return GraphQLMatchData("http://dab/graphql", httpx.AsyncClient(transport=httpx.MockTransport(dab)),
                            stats_wait=0)


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def dab():
    return FakeDab()


def test_match_info_from_the_ma1_payload(dab):
    info = run(client(dab).match_info(MATCH))
    assert (info.home.name, info.away.code, info.player("p-riv-09")) == ("Riverside FC", "HAR", "Mensah")


def test_events_cross_half_time_and_stop_at_the_second(dab):
    c = client(dab)
    for start, end, sec in [(MatchClock(1, 46), MatchClock(2, 46), 59), (MatchClock(1, 23), MatchClock(1, 23), 9),
                            (MatchClock(1, 0), MatchClock(2, 95), 59)]:
        got = run(c.events(MATCH, start, end, sec))
        assert got == sorted(run(FIXTURE.events(MATCH, start, end, sec)), key=lambda e: e["seq"])
    assert len(got) == len(FIXTURE.raw) > FakeDab.page_cap  # followed the cursor across pages


def test_ledger_period_end_and_related_event(dab):
    c = client(dab)
    ledger = run(c.key_events(MATCH, MatchClock(2, 53), 34))
    assert [k["keyType"] for k in ledger][-2:] == ["Goal", "VarOverturn"]
    assert len(run(c.key_events(MATCH, MatchClock(1, 23), 8))) == 0
    assert run(c.period_end(MATCH, 1)) == MatchClock(1, 47)
    assert run(c.period_end(MATCH, 2)) == MatchClock(2, 95)
    assert run(c.period_end(MATCH, 3)) is None
    assert run(c.raw_event(MATCH, "c-har", 405))["typeId"] == 16


def test_stats_as_of_uses_the_latest_minute_at_or_before(dab):
    c = client(dab)
    rows = run(c.stats_as_of(MATCH, MatchClock(1, 21)))
    assert {r["minuteLabel"] for r in rows} == {"21'"} and len(rows) == 2
    assert run(c.stats_as_of(MATCH, MatchClock(1, 19))) == []


def test_stats_waits_for_a_row_the_sql_write_has_not_landed(dab):
    dab.hidden_stats.add(MatchClock(1, 23))
    c = client(dab)

    async def reveal_after_two_tries():
        original = c._items
        calls = 0

        async def items(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                dab.hidden_stats.clear()
            return await original(*args, **kwargs)
        c._items = items
        return await c.stats_as_of(MATCH, MatchClock(1, 23), expect_row=True), calls

    rows, calls = run(reveal_after_two_tries())
    assert calls == 3 and rows[0]["minuteLabel"] == "24'"
    dab.hidden_stats.add(MatchClock(1, 23))
    assert run(client(dab).stats_as_of(MATCH, MatchClock(1, 23)))[0]["minuteLabel"] == "23'"  # quiet: no wait


def test_graphql_errors_are_raised(dab):
    with pytest.raises(GraphQLError, match="bogus"):
        run(client(dab)._post("{ bogus }", {}))


def test_orchestrator_over_graphql_matches_the_fixture_run(dab):
    messages = [m for _, m in read_notifications(NOTIFICATIONS) if m]

    def full_run(data):
        agents, store = FakeAgents(), MemoryStore()
        engine = MatchOrchestrator(MATCH, data, agents, store, MemorySink(store))

        async def go():
            for m in messages:
                await engine.handle(m)
        asyncio.run(go())
        return agents.calls

    via_graphql, via_fixture = full_run(client(dab)), full_run(FIXTURE)
    assert len(via_graphql) == len(via_fixture)
    for (agent_a, vars_a), (agent_b, vars_b) in zip(via_graphql, via_fixture):
        assert agent_a == agent_b
        assert {k: v for k, v in vars_a.items() if k != "game_state_statistics"} == \
               {k: v for k, v in vars_b.items() if k != "game_state_statistics"}
