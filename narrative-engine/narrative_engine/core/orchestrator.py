"""Decides what runs when for one match (docs/design/narrative-generation-engine.md §6, §10).

- MinuteClosed: summarise every unsummarised minute up to it, in order, then compress.
  Empty minutes get a fixed block without a model call. Each finished period collapses
  into one block and gets a half-time or full-time narrative step.
- KeyEventDetected: an author step for the active buckets (no debounce).
- Ten summarised minutes without a step: a scheduled author step.
- PresenceChanged: update the active buckets; a newly active bucket gets a catch-up step.

Each message is first *recorded* in the match checkpoint (closed minutes, the horizon and
a queue of pending narrative steps), then the *work* runs from the checkpoint in match-time
order: a step waits for the minutes that were closed when it was recorded (a key event,
a catch-up) or for its own minute (scheduled, half and full time), runs before any later
minute is summarised, and reads only up to the horizon recorded with it. So a backlog
gives the same output as live processing. `accept` records and wakes a
background worker, so a Service Bus message can be completed in milliseconds however slow
the models are; after a restart the worker resumes from the checkpoint. `handle` records
and waits for the work (tests and local runs). Recording is idempotent: block IDs and step
IDs are deterministic, and a step that is done or queued is not queued again. Author runs
are serialised per bucket and capped across buckets.
"""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from narrative_engine.context import compression
from narrative_engine.core.config import Settings
from narrative_engine.context.builder import ContextBuilder
from narrative_engine.core.models import (USER_TYPES, AgentResult, ContextBlock, KeyEventDetected, MatchClock, MinuteClosed,
                                     Narrative, PeriodChanged, PresenceChanged, Trigger, minutes_between, parse_time)
from narrative_engine.context.render import describe_key_event

EMPTY_MINUTE = "No recorded events in this minute."
log = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


def new_checkpoint():
    return {"status": "live", "lastSummarised": None, "closedThrough": None, "horizon": None, "periodEnds": {},
            "closedPeriods": [], "minutesSinceStep": 0, "presence": None, "pending": [], "done": []}


def active_user_types(checkpoint, now, stale_seconds):
    """Buckets with viewers, or all 12 when presence is missing or stale."""
    presence = checkpoint and checkpoint["presence"]
    if not presence or (now - parse_time(presence["receivedAt"])).total_seconds() > stale_seconds:
        return list(USER_TYPES)
    return [t for t in USER_TYPES if presence["counts"].get(t, 0) > 0]


class MatchOrchestrator:
    def __init__(self, match_id, data, agents, store, publisher, settings=Settings(), now=utcnow):
        self.match_id, self.data, self.agents, self.store, self.publisher = match_id, data, agents, store, publisher
        self.settings, self.now = settings, now
        self.context = ContextBuilder(data, store, settings.last_n_narratives)
        self.work_lock = asyncio.Lock()
        self.save_lock = asyncio.Lock()
        self.bucket_locks = defaultdict(asyncio.Lock)
        self.author_slots = asyncio.Semaphore(settings.author_concurrency)
        self.cp = None
        self.worker, self.wake = None, asyncio.Event()
        self.retry_backoff = 5.0  # seconds before the worker retries failed work; doubles to 120

    # --- state -----------------------------------------------------------------

    async def _load(self):
        if self.cp is None:
            self.cp = await self.store.get_checkpoint(self.match_id) or new_checkpoint()
            self.cp.setdefault("pending", [])
            self.cp.setdefault("done", [])

    async def _save(self):
        async with self.save_lock:  # one write at a time, each of the latest state
            await self.store.save_checkpoint(self.match_id, self.cp)

    def _clock(self, field):
        return MatchClock.parse(self.cp[field]) if self.cp[field] else None

    def _see(self, clock, second):
        """Advance the horizon: the latest point the ETL has announced."""
        horizon = self.cp["horizon"]
        if horizon is None or (clock.periodId, clock.timeMin, second) > tuple(horizon):
            self.cp["horizon"] = [clock.periodId, clock.timeMin, second]

    def active_buckets(self):
        return active_user_types(self.cp, self.now(), self.settings.presence_stale_seconds)

    def _queue(self, trigger, clock, horizon, buckets, after, key_row=None):
        """Add a narrative step to the checkpoint unless it is already done or queued; it runs once
        the minute `after` (a clock key, or None) is summarised."""
        if trigger.ref in self.cp["done"] or any(p["ref"] == trigger.ref for p in self.cp["pending"]):
            return
        self.cp["pending"].append({"type": trigger.type, "ref": trigger.ref, "reason": trigger.reason,
                                   "eventIds": list(trigger.eventIds), "clock": clock.key, "horizon": list(horizon),
                                   "buckets": list(buckets), "after": after, "keyRow": key_row})

    # --- recording ---------------------------------------------------------------

    async def handle(self, message):
        """Record the message, then do the work it makes due."""
        await self.record(message)
        await self.work()

    async def accept(self, message):
        """Record the message and leave the work to the background worker."""
        await self.record(message)
        self.kick()

    async def record(self, message):
        await self._load()
        if isinstance(message, MinuteClosed):
            self._see(message.clock, 59)
            closed = self._clock("closedThrough")
            if closed is None or message.clock > closed:
                self.cp["closedThrough"] = message.clock.key
        elif isinstance(message, KeyEventDetected):
            if self.cp["status"] != "live":
                return
            self._see(message.clock, message.timeSec)
            row = {"keyType": message.keyType, "detail": message.detail, "contestantId": message.contestantId,
                   "playerId": message.playerId, "timeSec": message.timeSec}
            self._queue(Trigger("keyEvent", f"key:{message.id}", "", (message.id,)), message.clock,
                        [message.clock.periodId, message.clock.timeMin, message.timeSec], self.active_buckets(),
                        self.cp["closedThrough"], row)
        elif isinstance(message, PresenceChanged):
            previous = self.cp["presence"]
            if previous and message.sentAt <= parse_time(previous["sentAt"]):
                return
            before = set(self.active_buckets())
            self.cp["presence"] = {"counts": dict(message.activeUserTypes), "sentAt": message.sentAt.isoformat(),
                                   "receivedAt": self.now().isoformat()}
            joined = [t for t in self.active_buckets() if t not in before]
            if joined and self.cp["status"] == "live" and self.cp["horizon"] is not None:
                p, m, _ = self.cp["horizon"]
                reason = "A viewer of this type has just joined. Bring them up to date with the match so far."
                for t in joined:
                    self._queue(Trigger("catchUp", f"catchUp:{t}:{message.sentAt.isoformat()}", reason),
                                MatchClock(p, m), self.cp["horizon"], [t], self.cp["closedThrough"])
        elif not isinstance(message, PeriodChanged):  # PeriodEnded: the work looks the period end up
            return
        await self._save()

    # --- background worker -------------------------------------------------------

    def kick(self):
        self.wake.set()
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._run())

    async def _run(self):
        delay = self.retry_backoff
        while self.wake.is_set():
            self.wake.clear()
            try:
                await self.work()
                delay = self.retry_backoff
            except Exception:
                log.exception("%s: work failed; retrying in %.0fs", self.match_id, delay)
                self.wake.set()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)

    # --- work ----------------------------------------------------------------------

    async def work(self):
        """Steps and minute summaries in match-time order, until nothing is due."""
        await self._load()
        async with self.work_lock:
            while True:
                closed = self._clock("closedThrough")
                ends = await self._period_ends(closed.periodId) if closed else {}
                due = self._next_minute(ends)
                last = self._clock("lastSummarised")
                ready = [p for p in self.cp["pending"]
                         if p["after"] is None or (last is not None and MatchClock.parse(p["after"]) <= last)]
                if ready:
                    await self._run_step(min(ready, key=lambda p: tuple(p["horizon"])))
                elif due is not None:
                    await self._summarise_minute(due, ends)
                elif await self._close_periods(ends):
                    await self._save()
                else:
                    return

    async def _run_step(self, pending):
        clock = MatchClock.parse(pending["clock"])
        reason = pending["reason"]
        if pending["keyRow"]:
            row = pending["keyRow"]
            info = await self.data.match_info(self.match_id)
            reason = f"Key event at {clock.label} ({clock.timeMin:02d}:{row['timeSec']:02d}): " \
                     f"{describe_key_event(row, info)}"
        trigger = Trigger(pending["type"], pending["ref"], reason, tuple(pending["eventIds"]))
        p, m, s = pending["horizon"]
        await self._step(trigger, clock, pending["buckets"], (MatchClock(p, m), s))
        self.cp["pending"] = [x for x in self.cp["pending"] if x["ref"] != pending["ref"]]
        self.cp["done"].append(pending["ref"])
        await self._save()

    async def _period_ends(self, through_period):
        ends = self.cp["periodEnds"]
        for period in range(1, through_period + 1):
            if str(period) not in ends and (end := await self.data.period_end(self.match_id, period)):
                ends[str(period)] = end.key
        return {int(p): MatchClock.parse(k) for p, k in ends.items()}

    def _next_minute(self, ends):
        """The next closed minute without a summary, or None."""
        target = self._clock("closedThrough")
        due = minutes_between(self._clock("lastSummarised"), target, ends.get) if target else None
        return due[0] if due else None

    async def _summarise_minute(self, clock, ends):
        await self._summarise(clock)
        self.cp["lastSummarised"] = clock.key
        self.cp["minutesSinceStep"] += 1
        await self._compress()
        if self.cp["minutesSinceStep"] >= self.settings.fallback_minutes and self.cp["status"] == "live":
            self.cp["minutesSinceStep"] = 0
            reason = f"Scheduled update at {clock.label}: no narrative step in the last " \
                     f"{self.settings.fallback_minutes} minutes."
            self._queue(Trigger("scheduled", f"scheduled:{clock.key}", reason), clock,
                        [clock.periodId, clock.timeMin, 59], self.active_buckets(), clock.key)
        await self._close_periods(ends)
        await self._save()

    def _block_id(self, span):
        return f"block:{self.match_id}:{span.key}"

    async def _summarise(self, clock):
        events = await self.data.events(self.match_id, clock, clock)
        if events:
            result = await self.agents.summarise(await self.context.summary_variables(self.match_id, clock, events))
        else:
            result = AgentResult(EMPTY_MINUTE, promptVersion="fixed-empty")
        span = compression.minute(clock)
        await self.store.put_block(ContextBlock(
            self._block_id(span), self.match_id, span.level, clock, clock, result.text, clock, result.model,
            result.promptVersion, result.tokens, self.now().isoformat()))

    async def _merge(self, merge):
        blocks = {b.id: b for b in await self.store.active_blocks(self.match_id)}
        inputs = [blocks[self._block_id(s)] for s in merge.inputs]
        output = merge.output
        variables = await self.context.compression_variables(self.match_id, inputs, output.end)
        result = await self.agents.compress(variables)
        block = ContextBlock(self._block_id(output), self.match_id, output.level, output.start, output.end,
                             result.text, output.end, result.model, result.promptVersion, result.tokens,
                             self.now().isoformat())
        await self.store.supersede(block, [b.id for b in inputs])

    async def _spans(self):
        return [compression.Span(b.level, b.coversFrom, b.coversTo) for b in await self.store.active_blocks(self.match_id)]

    async def _compress(self):
        while (merge := compression.next_compression(await self._spans())) is not None:
            await self._merge(merge)

    async def _close_periods(self, ends):
        """Collapse each finished, fully summarised period and queue its narrative step."""
        closed, last = False, self._clock("lastSummarised")
        for period, end in sorted(ends.items()):
            if period in self.cp["closedPeriods"] or last is None or last < end:
                continue
            if merge := compression.close_period(await self._spans(), period):
                await self._merge(merge)
            self.cp["closedPeriods"].append(period)
            self.cp["minutesSinceStep"] = 0
            horizon = [end.periodId, end.timeMin, 59]
            if period >= self.settings.final_period:
                self._queue(Trigger("fullTime", f"fullTime:{period}", "Full time."), end, horizon,
                            self.active_buckets(), end.key)
                self.cp["status"] = "complete"
            else:
                self._queue(Trigger("halfTime", f"halfTime:{period}", "Half time."), end, horizon,
                            self.active_buckets(), end.key)
            closed = True
        return closed

    # --- narrative steps ----------------------------------------------------------

    async def _step(self, trigger, clock, buckets, horizon):
        if trigger.type != "catchUp":
            self.cp["minutesSinceStep"] = 0
        step_id = f"{self.match_id}:{trigger.ref}"
        # Let every bucket finish before raising, so one failed author call doesn't cancel the rest;
        # a retry then only redoes the buckets without a narrative for this step.
        results = await asyncio.gather(*(self._author(t, trigger, step_id, clock, horizon) for t in buckets),
                                       return_exceptions=True)
        if errors := [r for r in results if isinstance(r, BaseException)]:
            raise errors[0]

    async def _author(self, user_type, trigger, step_id, clock, horizon):
        async with self.bucket_locks[user_type]:
            if existing := await self.store.narrative_for_step(self.match_id, user_type, step_id):
                # Stored but maybe not sent (the publish failed and the step is being retried): send
                # again. Delivery is at least once; the topic and consumers deduplicate on id.
                await self.publisher.publish(existing)
                return
            variables = await self.context.author_variables(self.match_id, user_type, trigger, horizon)
            async with self.author_slots:
                result = await self.agents.author(variables)
            previous = await self.store.narratives(self.match_id, user_type)
            seq = max((n.seq for n in previous), default=0) + 1
            narrative = Narrative(f"narr:{self.match_id}:{user_type}:{seq}", self.match_id, user_type, seq, step_id,
                                  trigger, clock, result.text.strip(), result.model, result.promptVersion,
                                  result.tokens, self.now().isoformat())
            await self.store.add_narrative(narrative)  # persist before publishing
            await self.publisher.publish(narrative)
