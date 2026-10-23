"""A fake-agent run over the whole Riverton Rovers–United recording with its SPADL actions
(tests/riverton_forgeham.py; synthetic). Live, the ETL holds only what has arrived when each
notification is sent; as a backlog it already holds the whole match. Both runs must build the
same prompts, so the engine reads nothing past each step's horizon and its output does not
depend on how far behind it runs."""
import asyncio

import riverton_forgeham
from support import EtlAsOf
from doubles.fake_agents import FakeAgents
from narrative_engine.core.models import parse_notification
from narrative_engine.core.orchestrator import MatchOrchestrator
from doubles.targets import StaticTargets, default_targets
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink


def run(backlog):
    data = EtlAsOf(riverton_forgeham.REPLAY, stats=riverton_forgeham.golden_stats(), actions_path=riverton_forgeham.ACTIONS,
                   keys=riverton_forgeham.key_rows())
    agents, store = FakeAgents(), MemoryStore()
    engine = MatchOrchestrator(riverton_forgeham.MATCH, data, agents, store, MemorySink(store),
                               targets=StaticTargets(default_targets()[:3]))

    async def go():
        for body, seq in riverton_forgeham.timeline():
            data.limit = None if backlog else seq
            await engine.record(parse_notification(body))
            if not backlog:
                await engine.work()
        data.limit = None
        await engine.work()
    asyncio.run(go())
    return agents.calls, asyncio.run(store.narratives(riverton_forgeham.MATCH)), engine.cp["status"]


def test_backlog_builds_the_same_prompts_as_live():
    live, backlog = run(backlog=False), run(backlog=True)
    calls, narratives, status = live
    assert status == "complete" and calls == backlog[0]
    assert [(n.stepId, n.text, n.eventSeq) for n in narratives] == [(n.stepId, n.text, n.eventSeq) for n in backlog[1]]
    summaries = [v["match_events"] for a, v in calls if a == "summarise"]
    assert len(summaries) == 94 and sum("key event: Goal for" in s for s in summaries) == 2
    lines = [line.split(": ", 1)[1] for s in summaries for line in s.splitlines() if ": " in line]
    shown = sum(line.startswith(("shot, ", "shot_penalty, ", "shot_freekick, ")) for line in lines)
    assert shown == 14  # every SPADL shot of the match, each in exactly one minute summary
    authors = [v for a, v in calls if a == "author"]
    assert any("Score: Riverton Rovers (home) 1 - 1 Forgeham United (away)" in v["game_state_statistics"] for v in authors)
