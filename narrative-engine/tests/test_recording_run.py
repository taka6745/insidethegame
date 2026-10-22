"""A fake-agent run over the whole Riverton Rovers–United recording with its SPADL actions
(tests/riverton_forgeham.py; synthetic). Live, the ETL holds only what has arrived when each
notification is sent; as a backlog it already holds the whole match. Both runs must build the
same prompts, so the engine reads nothing past each step's horizon and its output does not
depend on how far behind it runs."""
import asyncio

import riverton_forgeham
from narrative_engine.devtools.fake_agents import FakeAgents
from narrative_engine.core.models import MatchClock, parse_notification
from narrative_engine.core.orchestrator import MatchOrchestrator
from narrative_engine.devtools.fixture_data import FixtureMatchData
from narrative_engine.devtools.targets import StaticTargets, default_targets
from narrative_engine.match_data import EtlBehind
from narrative_engine.store.memory import MemoryStore
from narrative_engine.transport.files import MemorySink


class EtlAsOf(FixtureMatchData):
    """The ETL as of canonical seq `limit`: later MA3 rows, key events and unsettled actions do not
    exist yet, and SPADL reads past it are refused as the GraphQL client refuses them."""
    limit = None

    def _here(self, rows):
        return [r for r in rows if self.limit is None or r["eventSeq"] <= self.limit]

    async def events(self, match_id, start, end, until_sec=59):
        return self._here(await super().events(match_id, start, end, until_sec))

    async def event_seq(self, match_id, until, until_sec=59):
        bound = (until.periodId, until.timeMin, until_sec)
        return max((e["eventSeq"] for e in self._here(self.raw)
                    if (e["periodId"], e["timeMin"], e["timeSec"]) <= bound), default=None)

    def _converted(self, seq):
        if self.limit is not None and (seq or 0) > self.limit:
            raise EtlBehind(f"seq {seq} is past the ETL's {self.limit}")

    async def actions(self, match_id, after_seq, seq):
        self._converted(seq)
        return await super().actions(match_id, after_seq, seq)

    async def stats_at(self, match_id, seq):
        self._converted(seq)
        return await super().stats_at(match_id, seq)

    async def trends_at(self, match_id, seq):
        self._converted(seq)
        return await super().trends_at(match_id, seq)

    async def spells_at(self, match_id, seq):
        self._converted(seq)
        return await super().spells_at(match_id, seq)

    async def key_events(self, match_id, until, until_sec=59):
        seqs = {e["id"]: e["eventSeq"] for e in self.raw}
        return [k for k in await super().key_events(match_id, until, until_sec)
                if self.limit is None or seqs[k["id"]] <= self.limit]

    async def period_end_at(self, match_id, period_id):
        end = next((e for e in self._here(self.raw) if e["typeId"] == 30 and e["periodId"] == period_id), None)
        return (MatchClock(end["periodId"], end["timeMin"]), end["timeSec"]) if end else None


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
