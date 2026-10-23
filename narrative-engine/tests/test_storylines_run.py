"""Storylines over the whole Riverton Rovers–Forgeham United recording (synthetic) with fake agents, and ETL's Python twin of
the trend procedures (etl/reference/trends.py) serving the trends. Live (the ETL holds only what has arrived)
and as a backlog (it holds the whole match), the analyst and author get the same prompts, and the analyses
and storylines are the same. Expectations come from the recording, so a re-rendered one needs no edit."""
import asyncio
from functools import cache

import riverton_forgeham
from support import EtlAsOf, spells_at, trends_at
from narrative_engine.agents.prompt_source import PLACEHOLDER, shipped
from narrative_engine.api import schema
from narrative_engine.core.models import MatchClock, parse_notification
from narrative_engine.core.orchestrator import MatchOrchestrator, stoppage
from doubles.fake_agents import FakeAgents
from doubles.targets import StaticTargets, default_targets
from narrative_engine.service import Router
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink

def run(backlog):
    data = EtlAsOf(riverton_forgeham.REPLAY, stats=riverton_forgeham.golden_stats(), actions_path=riverton_forgeham.ACTIONS,
                   keys=riverton_forgeham.key_rows(), trends=trends_at, spells=spells_at)
    agents, store = FakeAgents(), MemoryStore()
    targets = StaticTargets(default_targets()[:3])
    engine = MatchOrchestrator(riverton_forgeham.MATCH, data, agents, store, MemorySink(store), targets=targets)

    async def go():
        for body, seq in riverton_forgeham.timeline():
            data.limit = None if backlog else seq
            await engine.record(parse_notification(body))
            if not backlog:
                await engine.work()
        data.limit = None
        await engine.work()
        return (await store.analyses(riverton_forgeham.MATCH), await store.storylines(riverton_forgeham.MATCH),
                await store.narratives(riverton_forgeham.MATCH))
    analyses, lines, narratives = asyncio.run(go())
    return {"calls": agents.calls, "analyses": analyses, "storylines": lines, "narratives": narratives,
            "data": data, "agents": agents, "store": store, "targets": targets}


@cache
def runs():
    return run(backlog=False), run(backlog=True)


def test_backlog_and_live_give_the_same_analyses_storylines_and_prompts():
    live, backlog = runs()
    assert live["calls"] == backlog["calls"]
    strip = lambda docs: [{k: v for k, v in d.items() if k != "createdAt"} for d in docs]
    assert strip(live["analyses"]) == strip(backlog["analyses"]) and live["storylines"] == backlog["storylines"]
    key = lambda n: (n.stepId, n.userType, n.text, n.eventSeq, n.analysisId, n.storylineIds)
    assert [key(n) for n in live["narratives"]] == [key(n) for n in backlog["narratives"]]


def test_analyses_run_every_five_minutes_and_at_half_and_full_time():
    live, _ = runs()
    played = sorted({MatchClock(e["periodId"], e["timeMin"]) for e in riverton_forgeham.ma3()})
    ends = {p: max(c for c in played if c.periodId == p) for p in (1, 2)}
    due = [c for c in played if (c.timeMin + 1) % 5 == 0 and not stoppage(c) and c != ends[c.periodId]]
    refs = [a["ref"] for a in live["analyses"]]
    assert refs == [f"analysis:{c.key}" for c in due[:9]] + ["analysis:halfTime:1"] + \
        [f"analysis:{c.key}" for c in due[9:]] + ["analysis:fullTime:2"]
    assert len(refs) == len(due) + 2


def test_every_observation_is_grounded_and_every_storyline_resolves_at_full_time():
    live, _ = runs()
    analyses = live["analyses"]
    assert all(a["rejected"] == [] for a in analyses)  # the fake cites the numbers as shown
    assert sum(len(a["observations"]) for a in analyses) > len(analyses)
    for a in analyses:
        for o in a["observations"]:
            assert all(f in trends_at(a["eventSeq"]) or f["indicator"] in ("goals", "red_cards") for f in o["facts"])
        assert sum(s["status"] == "active" for s in a["storylines"]) <= 4
    final = analyses[-1]
    assert final["ref"] == "analysis:fullTime:2" and final["storylines"]
    assert all(s["status"] == "resolved" for s in final["storylines"]) and live["storylines"] == final["storylines"]
    assert any(s["keyEventIds"] for s in final["storylines"])  # goals linked by rule
    assert {s["outcome"] for s in final["storylines"]} & {"Full time."}


def test_every_author_step_after_ten_minutes_advances_a_shared_focus_storyline():
    live, _ = runs()
    narratives = live["narratives"]
    late = [n for n in narratives if n.matchTime > MatchClock(1, 9)]
    assert late and all(n.storylineIds and n.analysisId for n in late)
    by_step = {}
    for n in narratives:
        by_step.setdefault(n.stepId, set()).add(tuple(n.storylineIds))
    assert all(len(focus) == 1 for focus in by_step.values())  # every bucket advances the same storyline
    assert len({n.storylineIds[0] for n in late}) > 1  # the threads take turns
    assert any(n.trigger.type == "storylineTurn" for n in narratives)
    authors = [v for a, v in live["calls"] if a == "author"]
    assert all("FOCUS " in v["storylines"] for v in authors[-3:])


def test_prompts_take_exactly_the_engine_variables():
    live, _ = runs()
    for agent, role in (("analyse", "match-analyst"), ("author", "narrative-author")):
        variables = next(v for a, v in live["calls"] if a == agent)
        assert PLACEHOLDER.findall(shipped(role).template) and \
            set(PLACEHOLDER.findall(shipped(role).template)) == set(variables) - {"bucket_id"}, role


def test_graphql_serves_storylines_and_the_narratives_focus():
    live, _ = runs()
    query = """query ($m: String!, $u: String!) {
      storylines(matchId: $m) { id label status outcome beats { at { label } headline analysisId } keyEventIds }
      narratives(matchId: $m, userType: $u, first: 200) { items { analysisId storylineIds triggerType } } }"""
    result = asyncio.run(schema.execute(query, {"m": riverton_forgeham.MATCH, "u": "home:simple"},
                                        context_value={"store": live["store"]}))
    assert result.errors is None
    lines = result.data["storylines"]
    assert [x["id"] for x in lines] == [x["id"] for x in live["storylines"]] and all(x["status"] == "resolved" for x in lines)
    items = result.data["narratives"]["items"]
    assert {i["storylineIds"][0] for i in items if i["storylineIds"]} <= {x["id"] for x in lines}


def test_purge_removes_analyses_and_storylines():
    live, _ = runs()
    router = Router(live["data"], live["agents"], live["store"], MemorySink(), targets=live["targets"])
    result = asyncio.run(router.purge(riverton_forgeham.MATCH))
    assert result["purged"]["analyses"] == len(live["analyses"]) > 0
    assert result["purged"]["storylines"] == len(live["storylines"]) > 0
    assert asyncio.run(live["store"].analyses(riverton_forgeham.MATCH)) == []
    assert asyncio.run(live["store"].storylines(riverton_forgeham.MATCH)) == []
    assert riverton_forgeham.MATCH in asyncio.run(live["store"].tombstones())[0]
