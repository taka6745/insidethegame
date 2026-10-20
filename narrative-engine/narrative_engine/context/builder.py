"""Builds each agent's prompt variables from the store and the ETL.

Reads never go past the horizon: the latest (clock, second) announced by an ETL
notification. Statistics come from the last summarised minute, because a minute's
statistics are only complete once its MinuteClosed has arrived.
"""
from narrative_engine.core.models import PERIOD_START, MatchClock
from narrative_engine.context.render import (PERIOD_NAMES, render_events, render_ledger, render_match, render_stats)


def render_blocks(blocks):
    if not blocks:
        return "No match context yet."
    lines = []
    for b in blocks:
        span = b.coversFrom.label if b.coversFrom == b.coversTo else f"{b.coversFrom.label}-{b.coversTo.label}"
        lines.append(f"[{span}, {PERIOD_NAMES.get(b.coversFrom.periodId, '')}] {b.summary}")
    return "\n".join(lines)


class ContextBuilder:
    def __init__(self, data, store, last_n=5):
        self.data, self.store, self.last_n = data, store, last_n

    async def _stats(self, match_id, info, clock, expect_row=False):
        rows = await self.data.stats_as_of(match_id, clock, expect_row) if clock else []
        return f"{render_match(info)}\n{render_stats(rows, info)}"

    async def summary_variables(self, match_id, clock, events):
        info = await self.data.match_info(match_id)
        return {"game_state_statistics": await self._stats(match_id, info, clock, expect_row=bool(events)),
                "match_events": render_events(events, info)}

    async def compression_variables(self, match_id, inputs, end):
        info = await self.data.match_info(match_id)
        return {"game_state_statistics": await self._stats(match_id, info, end), "summaries": render_blocks(inputs)}

    async def overturned(self, match_id, ledger):
        """keyEvents ids of goals that a later VarOverturn cancelled (qualifier 55 = Opta eventId)."""
        ids = set()
        for row in ledger:
            if row["keyType"] == "VarOverturn" and row.get("relatedEventId") is not None:
                goal = await self.data.raw_event(match_id, row["contestantId"], int(row["relatedEventId"]))
                if goal:
                    ids.add(goal["id"])
        return ids

    async def author_variables(self, match_id, user_type, trigger, horizon):
        """`horizon` is (MatchClock, second): nothing after it is read."""
        info = await self.data.match_info(match_id)
        blocks = await self.store.active_blocks(match_id)
        last_summarised = blocks[-1].coversTo if blocks else None
        clock, second = horizon
        start = last_summarised.next() if last_summarised else MatchClock(1, PERIOD_START[1])
        events = await self.data.events(match_id, start, clock, second) if start <= clock else []
        ledger = await self.data.key_events(match_id, clock, second)
        previous = (await self.store.narratives(match_id, user_type))[-self.last_n:]
        return {
            "user_type": user_type,
            "trigger_reason": trigger.reason,
            "game_state_statistics": await self._stats(match_id, info, last_summarised),
            "key_event_ledger": render_ledger(ledger, info, await self.overturned(match_id, ledger)),
            "combined_match_context": render_blocks(blocks),
            "match_events": render_events(events, info),
            "narrative_excerpts": "\n".join(f"- {n.text}" for n in previous) or "None yet.",
        }
