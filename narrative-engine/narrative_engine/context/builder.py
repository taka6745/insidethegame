"""Builds each agent's prompt variables from the store and the ETL.

Reads never go past the horizon: the latest (clock, second) announced by an ETL
notification. MA3 rows and key events are read by clock; SPADL actions and catalogue stats
by `seq`, the canonical seq of the latest MA3 row up to that clock. A window of play from
minute `start` to the horizon holds the actions settled in it (finalSeq after the seq at the
end of the minute before `start`, up to the horizon's), so every action is shown exactly once,
in the window in which it became final. Statistics come from the last summarised minute,
because a minute is only complete once its MinuteClosed has arrived.
"""
from narrative_engine.analysis.policy import ShippedPolicy
from narrative_engine.analysis.validator import ledger_facts
from narrative_engine.context.compression import HALF
from narrative_engine.core.models import PERIOD_START, MatchClock
from narrative_engine.context.render import (PERIOD_NAMES, render_events, render_ledger,
                                             render_match, render_spells, render_stats, render_storylines,
                                             render_trend_table, render_trends)


def upto(rows, clock, second=59):
    return [r for r in rows if (r["periodId"], r["timeMin"], r["timeSec"]) <= (clock.periodId, clock.timeMin, second)]


def since(rows, start):
    return [r for r in rows if (r["periodId"], r["timeMin"]) >= (start.periodId, start.timeMin)]


def render_blocks(blocks):
    if not blocks:
        return "No match context yet."
    lines = []
    for b in blocks:
        span = b.coversFrom.label if b.coversFrom == b.coversTo else f"{b.coversFrom.label}-{b.coversTo.label}"
        lines.append(f"[{span}, {PERIOD_NAMES.get(b.coversFrom.periodId, '')}] {b.summary}")
    return "\n".join(lines)


class ContextBuilder:
    def __init__(self, data, store, last_n=5, policy=None):
        self.data, self.store, self.last_n = data, store, last_n
        self.policy = policy or ShippedPolicy()  # the storyline policy's prompt limits (`storylines` section)

    async def blocks(self, match_id, clock, second):
        """The context blocks a step at (clock, second) may read: the widest blocks covering only minutes complete
        by then (the horizon's own minute only at its last second or a period end). Normally the active blocks;
        a step recorded after later minutes were summarised (messages handled out of order) gets their
        superseded inputs instead, so it never reads past its horizon."""
        fits = lambda b: b.coversTo < clock or (b.coversTo == clock and (second >= 59 or b.tier == HALF))
        active = await self.store.active_blocks(match_id)
        if all(map(fits, active)):
            return active
        out = []
        for b in sorted(filter(fits, await self.store.all_blocks(match_id)), key=lambda b: b.coversFrom):
            if out and b.coversFrom <= out[-1].coversTo:  # nested: keep the wider of two with one start
                if b.coversFrom == out[-1].coversFrom and (b.coversTo, b.level) > (out[-1].coversTo, out[-1].level):
                    out[-1] = b
                continue
            out.append(b)
        return out

    async def _seq(self, match_id, clock, second=59):
        return await self.data.event_seq(match_id, clock, second) or 0

    async def _stats(self, match_id, info, clock, keys):
        """Catalogue stats at the end of `clock`; `keys` are the key events up to it (for the score)."""
        if clock is None:
            return f"{render_match(info)}\nNo statistics yet."
        rows = await self.data.stats_at(match_id, await self._seq(match_id, clock))
        return f"{render_match(info)}\n{render_stats(rows, info, clock, keys)}"

    async def _play(self, match_id, info, start, upto_seq, events, keys):
        """Play from minute `start` to canonical seq `upto_seq`: settled actions, MA3 facts and key events."""
        before = await self._seq(match_id, MatchClock(start.periodId, start.timeMin - 1))
        actions = await self.data.actions(match_id, before, upto_seq)
        events = [e for e in events if e.get("eventSeq", 0) <= upto_seq]
        return render_events(info, actions, events, since(keys, start), start)

    async def summary_variables(self, match_id, clock, events):
        info = await self.data.match_info(match_id)
        keys = await self.data.key_events(match_id, clock)
        return {"game_state_statistics": await self._stats(match_id, info, clock, keys),
                "match_events": await self._play(match_id, info, clock, await self._seq(match_id, clock), events,
                                                 keys)}

    async def compression_variables(self, match_id, inputs, end):
        info = await self.data.match_info(match_id)
        keys = await self.data.key_events(match_id, end)
        return {"game_state_statistics": await self._stats(match_id, info, end, keys),
                "summaries": render_blocks(inputs)}

    async def overturned(self, match_id, ledger):
        """keyEvents ids of goals that a later VarOverturn cancelled (qualifier 55 = Opta eventId)."""
        ids = set()
        for row in ledger:
            if row["keyType"] == "VarOverturn" and row.get("relatedEventId") is not None:
                goal = await self.data.raw_event(match_id, row["contestantId"], int(row["relatedEventId"]))
                if goal:
                    ids.add(goal["id"])
        return ids

    async def analysis_variables(self, match_id, reason, horizon, seq, storylines):
        """The analyst's variables at `horizon` (MatchClock, second) and canonical `seq`, plus what the
        validator and reducer need: (variables, {"trends", "ledger", "info"}). The analyst sees every served
        trend row and spell, plus the ledger's goals and red cards as rows it can cite."""
        info = await self.data.match_info(match_id)
        rules = (await self.policy.current()).storylines
        clock, second = horizon
        ledger = await self.data.key_events(match_id, clock, second)
        trends, spells = await self.data.trends_at(match_id, seq), await self.data.spells_at(match_id, seq)
        blocks = await self.blocks(match_id, clock, second)
        last = blocks[-1].coversTo if blocks else None
        variables = {
            "analysis_reason": reason,
            "game_state_statistics": await self._stats(match_id, info, last, upto(ledger, last) if last else []),
            "key_event_ledger": render_ledger(ledger, info, await self.overturned(match_id, ledger)),
            "combined_match_context": render_blocks(blocks),
            "match_trends": f"{render_trend_table(trends + ledger_facts(ledger, info), info)}\n"
                            f"Spells:\n{render_spells(spells, info)}",
            "storylines": render_storylines(storylines, info, ledger, beats=rules["beats_shown"]),
        }
        return variables, {"trends": trends, "ledger": ledger, "info": info}

    async def story_variables(self, match_id, horizon, seq, storylines, focus, focus_note=True):
        """The author's {storylines} (focus marked, no ids) and {match_trends} (flagged rows), shared by
        every bucket of one step."""
        info = await self.data.match_info(match_id)
        rules = (await self.policy.current()).storylines
        clock, second = horizon
        ledger = await self.data.key_events(match_id, clock, second)
        recent = clock.timeMin - rules["resolved_shown_minutes"]  # Opta minutes run on across periods
        shown = [s for s in storylines if s["status"] != "resolved" or s["id"] == focus or s["resolvedAt"] and
                 s["resolvedAt"]["timeMin"] >= recent]
        note = "\nNo focus storyline for this step." if focus_note and not focus else ""
        return {"storylines": render_storylines(shown, info, ledger, focus=focus, ids=False,
                                                beats=rules["beats_shown"]) + note,
                "match_trends": render_trends(await self.data.trends_at(match_id, seq), info, flagged_only=True,
                                              always=rules["author_match_indicators"])}

    async def follow_variables(self, match_id, horizon, seq, storylines):
        """The story-follow decision state's match inputs, as the author sees them at `horizon` and `seq`:
        statistics, the key event ledger, the match context, the storylines and the flagged trends."""
        info = await self.data.match_info(match_id)
        clock, second = horizon
        blocks = await self.blocks(match_id, clock, second)
        last_summarised = blocks[-1].coversTo if blocks else None
        ledger = await self.data.key_events(match_id, clock, second)
        return {"game_state_statistics": await self._stats(match_id, info, last_summarised,
                                                           upto(ledger, last_summarised) if last_summarised else []),
                "key_event_ledger": render_ledger(ledger, info, await self.overturned(match_id, ledger)),
                "combined_match_context": render_blocks(blocks),
                **await self.story_variables(match_id, horizon, seq, storylines, None, focus_note=False)}

    async def author_variables(self, match_id, user_type, audience, trigger, horizon, seq=None, story=None,
                               before=None):
        """`horizon` is (MatchClock, second) and `seq` the step's canonical seq (default: the latest
        up to the horizon): nothing after them is read. `audience` is the bucket's framing text,
        filled into the prompt's {user_type}; `story` the step's `story_variables`. The bucket's narratives are
        those written from data up to the horizon, or (`before`: [period, minute, second], story follows) before it."""
        info = await self.data.match_info(match_id)
        clock, second = horizon
        blocks = await self.blocks(match_id, clock, second)
        last_summarised = blocks[-1].coversTo if blocks else None
        start = last_summarised.next() if last_summarised else MatchClock(1, PERIOD_START[1])
        ledger = await self.data.key_events(match_id, clock, second)
        if seq is None:
            seq = await self._seq(match_id, clock, second)
        if start <= clock:
            events = await self.data.events(match_id, start, clock, second)
            play = await self._play(match_id, info, start, seq, events, ledger)
        else:
            play = render_events(info, [])
        at = lambda n: (n.matchTime.periodId, n.matchTime.timeMin, n.timeSec or 0)
        shown = (lambda n: at(n) < tuple(before)) if before is not None \
            else (lambda n: at(n) <= (clock.periodId, clock.timeMin, second))
        previous = [n for n in await self.store.narratives(match_id, user_type) if shown(n)]
        previous = previous[-self.last_n:]
        stats_keys = upto(ledger, last_summarised) if last_summarised else []
        return {
            "bucket_id": user_type,
            "user_type": audience,
            "trigger_reason": trigger.reason,
            "game_state_statistics": await self._stats(match_id, info, last_summarised, stats_keys),
            "key_event_ledger": render_ledger(ledger, info, await self.overturned(match_id, ledger)),
            "combined_match_context": render_blocks(blocks),
            "match_events": play,
            "narrative_excerpts": "\n".join(f"- {n.matchTime.label} {n.text}" for n in previous) or "None yet.",
            **(story or {"storylines": "No storylines yet.", "match_trends": "No trend data yet."}),
        }
