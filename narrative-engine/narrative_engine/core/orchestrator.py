"""Decides what runs when for one match (docs/design/narrative-generation-engine.md §6, §10).

- MinuteClosed: summarise every unsummarised minute up to it, in order, then compress.
  Empty minutes, and merges of only empty blocks, get a fixed block without a model call.
  Each finished period collapses into one block and gets a half-time or full-time narrative
  step; its last minute skips the regular compression and scheduled step, which that redoes.
  Nor is a scheduled step queued in stoppage time: the half-time or full-time step is minutes away.
- KeyEventDetected: an author step for the active buckets (no debounce), with the key event's `MomentClip`
  when the follow config clips its type (PLAN.md §10.2 D7).
- Ten summarised minutes without a step: a scheduled author step.
- At minutes 5, 10, 15 … (`analysis_minutes`) of each match, and at half and full time: a match analysis.
  The analyst reads the ETL's trends and names patterns in its own words, citing the numbers; the
  validator drops ungrounded observations and the reducer moves the storylines (analysis.storylines); the
  analysis is stored as an immutable snapshot and the storylines as its projection. A storyline it opens
  or resolves gets a `storylineTurn` author step (setting `storyline_turns`). Every author step advances
  one focus storyline, chosen here from the latest analysis and shared by all its buckets.
- Targets: the user backend's enabled buckets for this matchId (audience.targets), re-read on every
  message and by the router's poll; a newly enabled bucket gets a catch-up step, and a disabled one
  gets nothing after its in-flight steps. An empty list: nothing is written. Never read yet (backend
  down): steps wait for them.
- The match is complete once its final period (MA1 capabilities.periods) has ended and been summarised.

Each message is first *recorded* in the match checkpoint (closed minutes, the horizon and
a queue of pending narrative steps), then the *work* runs from the checkpoint in match-time
order: a step waits for the minutes that were closed when it was recorded (a key event,
a catch-up) or for its own minute (scheduled, half and full time), runs before any later
minute is summarised, and reads only up to the horizon recorded with it. So a backlog
gives the same output as live processing. `accept` records and wakes a
background worker, so a Service Bus message can be completed in milliseconds however slow
the models are; after a restart the worker resumes from the checkpoint. `handle` records
and waits for the work (tests and local runs). Recording is idempotent: block IDs and step
IDs are deterministic, and a step that is done or queued is not queued again. A match runs one
step at a time; a step's author calls run together (capped by `author_concurrency`), and each one
that fails leaves the others' narratives stored, so a retry redoes only the missing ones. Every
agent model call also takes a slot of the router's global `ModelGate`; decision calls do too unless
the decision model has its own capacity (`decision_slot`).
- Story follows (follows/): with the backend's followed topics and a decision model, each key event,
  minute recap, storyline update and period end also queues a `subscriptionEval` step that asks the
  decision model which followed topics moved and writes their narratives; a (topic, bucket) pair that
  appears mid-match gets a `subscriptionStart` step ("the story so far").
- Grounding: every excerpt is checked by analysis.validator (numbers, names, wording) and by the
  decision model's claim questions (the policy's `claims`: cause, intent, result, comparison), one call
  per step's drafts, with the policy's rewrites.
"""
import asyncio
import hashlib
import json
import logging
from contextlib import nullcontext
from datetime import datetime, timezone

from narrative_engine.analysis import storylines as story
from narrative_engine.analysis import validator as grounding
from narrative_engine.analysis.policy import PolicyUnavailable, ShippedPolicy
from narrative_engine.analysis.validator import parse, validate
from narrative_engine.context import compression
from narrative_engine.core.config import Settings
from narrative_engine.core.gate import ModelGate
from narrative_engine.context.builder import ContextBuilder
from narrative_engine.agents.prompt_source import PromptUnavailable, ShippedPrompts
from narrative_engine.audience.targets import framing
from narrative_engine.core.models import (AgentResult, BrokerUnavailable, ContextBlock, KeyEventDetected, MatchClock,
                                     MinuteClosed, Narrative, PERIOD_END, PeriodChanged, Trigger, merge_usage, minutes_between)
from narrative_engine.context.render import describe_key_event, score
from narrative_engine.decisions import DecisionError
from narrative_engine.follows.steps import FollowSteps
from narrative_engine.match_data import EtlBehind

EMPTY_MINUTE = "No recorded events in this minute."
EMPTY_SPAN = "No recorded events in these minutes."
FIXED_EMPTY = "fixed-empty"  # promptVersion of blocks written without a model call
log = logging.getLogger(__name__)


def stoppage(clock):
    """Past the period's regulation end (Opta timeMin 45 is the first added minute of the first half)."""
    return clock.timeMin >= PERIOD_END.get(clock.periodId, 120)


def utcnow():
    return datetime.now(timezone.utc)


def new_checkpoint():
    return {"status": "live", "lastSummarised": None, "closedThrough": None, "horizon": None, "periodEnds": {},
            "closedPeriods": [], "minutesSinceStep": 0, "targets": None, "pending": [], "done": [],
            "analysis": None, "focusLog": [], "follows": None, "followPairs": [], "followFired": {},
            "followRetries": [], "clips": None}


def active_user_types(checkpoint):
    """Bucket ids the engine is writing for: the last targets read from the user backend."""
    targets = checkpoint and checkpoint.get("targets")
    return [t["bucket_id"] for t in targets["items"]] if targets else []


class TargetsUnavailable(RuntimeError):
    pass


class Closed(RuntimeError):
    """The match was purged while this orchestrator was still working on it."""


class MatchOrchestrator:
    def __init__(self, match_id, data, agents, store, publisher, settings=Settings(), now=utcnow, targets=None,
                 prompts=None, gate=None, policy=None, follows=None, decisions=None):
        self.match_id, self.data, self.agents, self.store, self.publisher = match_id, data, agents, store, publisher
        self.settings, self.now = settings, now
        # Targets always come from the caller (the service: the backend's); there are no built-in buckets.
        if targets is None:
            raise ValueError("targets are required: the service passes the user backend's")
        self.targets = targets
        self.prompts = prompts or ShippedPrompts()
        self.policy = policy or ShippedPolicy()  # the service passes the backend's (analysis.policy)
        self.gate = gate or ModelGate(settings.model_concurrency)
        self.context = ContextBuilder(data, store, settings.last_n_narratives, self.policy)
        self.work_lock = asyncio.Lock()
        self.save_lock = asyncio.Lock()
        self.author_slots = asyncio.Semaphore(settings.author_concurrency)
        # Story follows: the backend's followed topics and the decision model (both, or no follow work); the
        # decision model also checks the analyst's and the authors' claims (the policy's `claims`).
        self.decisions = decisions
        self.follow = FollowSteps(self, follows, decisions)
        self.drafts = {}  # model drafts of the work item being retried (`_drafted`)
        self.cp = None
        self.worker, self.wake = None, asyncio.Event()
        self.closed = False

    # --- state -----------------------------------------------------------------

    async def _load(self):
        if self.cp is None:
            self.cp = await self.store.get_checkpoint(self.match_id) or new_checkpoint()
            self.cp.setdefault("pending", [])
            self.cp.setdefault("done", [])
            self.cp.setdefault("targets", None)
            self.cp.setdefault("analysis", None)
            self.cp.setdefault("focusLog", [])
            self.cp.setdefault("follows", None)

    async def _save(self):
        self._check_open()
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
        """The current targets, copied into each queued step so it writes for the buckets of its time;
        None while they have never been read (the step then reads them when it runs)."""
        targets = self.cp["targets"]
        return [{**t, "revision": targets["revision"]} for t in targets["items"]] if targets else None

    async def _sync_targets(self):
        """Read the user backend's audience targets, then its followed topics; True if either changed."""
        audience = await self._sync_audience()
        return await self.follow.sync() or audience

    async def _sync_audience(self):
        """Read the user backend's targets; True if they changed. A newly active bucket gets a catch-up."""
        try:
            targets = await self.targets.current(self.match_id)
        except Exception as error:  # keep the last known targets; the poll tries again
            log.warning("%s: audience targets unavailable (%s)", self.match_id, type(error).__name__)
            return False
        previous = self.cp["targets"]
        if previous and previous["revision"] == targets.revision:
            return False
        before = set(active_user_types(self.cp))
        self.cp["targets"] = {"revision": targets.revision, "items": list(targets.items)}
        horizon = self.cp["horizon"]
        joined = [t for t in self.active_buckets() or [] if t["bucket_id"] not in before]
        if previous is not None and joined and self.cp["status"] == "live" and horizon is not None:
            p, m, _ = horizon
            reason = "This audience has just been enabled. Bring them up to date with the match so far."
            for t in joined:
                self._queue(Trigger("catchUp", f"catchUp:{t['bucket_id']}:{targets.revision}", reason),
                            MatchClock(p, m), self.cp["horizon"], [t], self.cp["closedThrough"])
        return True

    async def sync_targets(self):
        """Poll entry point: record target changes, and wake the worker for any catch-up."""
        await self._load()
        if self.cp["status"] == "live" and await self._sync_targets():
            await self._save()
            self.kick()

    def _queue(self, trigger, clock, horizon, buckets, after, key_row=None, **extra):
        """Add a narrative step to the checkpoint unless it is already done or queued; it runs once
        the minute `after` (a clock key, or None) is summarised. True if queued."""
        if trigger.ref in self.cp["done"] or any(p["ref"] == trigger.ref for p in self.cp["pending"]):
            return False
        self.cp["pending"].append({"type": trigger.type, "ref": trigger.ref, "reason": trigger.reason,
                                   "eventIds": list(trigger.eventIds), "clock": clock.key, "horizon": list(horizon),
                                   "buckets": None if buckets is None else list(buckets), "after": after,
                                   "keyRow": key_row, **extra})
        return True

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
        changed = await self._sync_targets()
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
            horizon = [message.clock.periodId, message.clock.timeMin, message.timeSec]
            self._queue(Trigger("keyEvent", f"key:{message.id}", "", (message.id,)), message.clock, horizon,
                        self.active_buckets(), self.cp["closedThrough"], row)
            self.follow.queue_eval("keyEvent", f"key:{message.id}", "", message.clock, horizon,
                                   self.cp["closedThrough"], row, (message.id,))
        elif isinstance(message, PeriodChanged) and not message.started:
            await self._period_ended(message)
        elif not isinstance(message, PeriodChanged) and not changed:
            return
        await self._save()

    async def _period_ended(self, message):
        """The period is over: its last minute is closed now, at the End event's clock and second, so
        the half-time or full-time step runs without waiting for the ETL's MinuteClosed or idle flush.
        The clock comes from the notification itself (the SQL row can trail it), else from the ETL."""
        period = message.periodId
        if message.clock is not None:
            end = message.clock, message.timeSec
        else:
            end = await self.data.period_end_at(self.match_id, period)
        if end is None:  # not in the ETL yet: the work finds it with the minute's MinuteClosed
            return
        clock, second = end
        self.cp["periodEnds"][str(period)] = clock.key
        self.cp.setdefault("periodEndSeconds", {})[str(period)] = second
        self._see(clock, second)
        closed = self._clock("closedThrough")
        if closed is None or clock > closed:
            self.cp["closedThrough"] = clock.key

    # --- background worker -------------------------------------------------------

    def decision_slot(self):
        """A model-gate slot for a decision call, unless the decision model has its own capacity (Decision-1:
        its own deployment and request pacing), so waiting for it never holds back the agents' calls."""
        if getattr(self.decisions, "own_capacity", False):
            return nullcontext()
        return self.gate.slot(self.match_id, "decision")

    def kick(self):
        self.wake.set()
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._run())

    async def _run(self):
        delay = self.settings.retry_seconds
        while self.wake.is_set():
            self.wake.clear()
            try:
                await self.work()
                delay = self.settings.retry_seconds
            except Closed:
                return
            except Exception as error:
                if isinstance(error, (TargetsUnavailable, PromptUnavailable, PolicyUnavailable, EtlBehind,
                                      DecisionError, BrokerUnavailable)):  # waiting, not a fault
                    log.warning("%s: paused (%s); retrying in %.0fs", self.match_id, error, delay)
                else:
                    log.exception("%s: work failed; retrying in %.0fs", self.match_id, delay)
                self.wake.set()
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.settings.retry_max_seconds)

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
                if ready:  # an analysis first at the same horizon, so the steps there read it
                    await self._run_step(min(ready, key=lambda p: (tuple(p["horizon"]), p["type"] != "analysis")))
                elif due is not None:
                    await self._summarise_minute(due, ends)
                elif await self._close_periods(ends):
                    await self._save()
                else:
                    return

    def _key_reason(self, pending, info):
        clock, row = MatchClock.parse(pending["clock"]), pending["keyRow"]
        return f"Key event at {clock.label} ({clock.timeMin:02d}:{row['timeSec']:02d}): {describe_key_event(row, info)}"

    async def _buckets_now(self):
        """For a step queued before the targets were ever read."""
        await self._sync_targets()
        if (buckets := self.active_buckets()) is None:
            raise TargetsUnavailable(f"audience targets for {self.match_id} unavailable from the user backend")
        return buckets

    def _check_open(self):
        if self.closed:
            raise Closed(self.match_id)

    def _finish(self, pending):
        self.cp["pending"] = [x for x in self.cp["pending"] if x["ref"] != pending["ref"]]
        self.cp["done"].append(pending["ref"])
        self.drafts.clear()

    async def _drafted(self, call, *key):
        """A writing-model draft, reused while its work item is retried with the same inputs: when a later check
        fails (the decision model unavailable), the retry repeats the check, not the writing."""
        digest = hashlib.sha256(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()
        if digest not in self.drafts:
            self.drafts[digest] = await call()
        return self.drafts[digest]

    async def _run_step(self, pending):
        if pending["type"] == "analysis":
            return await self._run_analysis(pending)
        if pending["type"] in ("subscriptionEval", "subscriptionStart"):
            return await self.follow.run(pending)
        clock = MatchClock.parse(pending["clock"])
        reason = pending["reason"]
        if pending["keyRow"]:
            reason = self._key_reason(pending, await self.data.match_info(self.match_id))
        trigger = Trigger(pending["type"], pending["ref"], reason, tuple(pending["eventIds"]))
        if pending["buckets"] is None:  # queued before the targets were ever read
            pending["buckets"] = await self._buckets_now()
        if not pending.get("prompt") or "seq" not in pending:  # pinned on the first attempt, so a retry
            pending["prompt"] = pending.get("prompt") or (await self.prompts.current("narrative-author")).label
            pending["seq"] = await self._horizon_seq(pending)  # uses the same prompt, data and focus
            await self._pin_focus(pending)
            await self._save()
        prompt = await self.prompts.pinned("narrative-author", pending["prompt"])
        await self._publish_moment_clip(pending)
        p, m, s = pending["horizon"]
        await self._step(trigger, clock, pending["buckets"], (MatchClock(p, m), s), prompt, pending["seq"],
                         pending.get("analysisId"), pending.get("focus"))
        keep = (await self.policy.current()).storylines["focus_recent_steps"]  # all choose_focus reads
        self._finish(pending)
        if pending.get("focus"):
            self.cp["focusLog"] = (self.cp["focusLog"] + [pending["focus"]])[-keep:] if keep else []
        await self._save()
        # The gap between the step's data and the latest closed minute is this match's backlog.
        log.info("%s %s at %d-%02d:%02d for %d bucket(s); closed through %s", self.match_id, pending["ref"],
                 p, m, s, len(pending["buckets"]), self.cp["closedThrough"])

    async def _publish_moment_clip(self, pending):
        """A key event's clip on the shared narratives of the step's buckets (`MomentClip`, PLAN.md §10.2 D7), when
        the served clip settings (`clips.enabled`, `clips.shared`; read with the follow targets but kept apart, so no
        follow or decision model is needed) clip its `keyType`. Sent apart from the narratives, so their grounding
        never decides it; again on a retry (the backend keeps one per bucket and moment)."""
        clips = self.cp.get("clips")
        row = pending["keyRow"]
        if not (clips and clips["enabled"] and clips.get("shared") and row and row["keyType"] in clips["key_types"]
                and pending["type"] == "keyEvent" and pending["eventIds"] and pending["buckets"]):
            return
        event = pending["eventIds"][0]
        self._check_open()
        await self.publisher.publish_clip({
            "type": "MomentClip", "id": f"mclip:{self.match_id}:{event}", "matchId": self.match_id,
            "buckets": [b["bucket_id"] for b in pending["buckets"]], "eventId": event, "eventSeq": pending["seq"],
            "stepId": f"{self.match_id}:{pending['ref']}"})

    async def _storylines(self, analysis_id):
        doc = analysis_id and await self.store.get_analysis(self.match_id, analysis_id)
        return doc["storylines"] if doc else []

    async def _pin_focus(self, pending):
        """The latest analysis (all earlier analyses have run: they sort first) and the step's focus."""
        latest = self.cp["analysis"]
        pending["analysisId"] = latest and latest["id"]
        lines = await self._storylines(pending["analysisId"])
        rules = (await self.policy.current()).storylines
        chosen = story.choose_focus(lines, pending["type"], rules=rules, key_row=pending["keyRow"] and {
            **pending["keyRow"], "id": pending["eventIds"][0]}, turned=pending.get("turned"),
            analysis_id=pending["analysisId"], recent=self.cp["focusLog"])
        pending["focus"] = chosen and chosen["id"]

    # --- match analysis ----------------------------------------------------------------

    def _queue_analysis(self, ref, reason, clock, horizon):
        self._queue(Trigger("analysis", ref, reason), clock, horizon, [], clock.key)

    async def _run_analysis(self, pending):
        clock, (p, m, s) = MatchClock.parse(pending["clock"]), pending["horizon"]
        analysis_id = f"analysis:{self.match_id}:{pending['ref'].split(':', 1)[1]}"
        doc = await self.store.get_analysis(self.match_id, analysis_id)
        if doc is None:  # written once: a retry after a crash reuses it rather than asking the model again
            if not pending.get("prompt") or "seq" not in pending:
                pending["prompt"] = (await self.prompts.current("match-analyst")).label
                pending["seq"] = await self._horizon_seq(pending)
                await self._save()
            doc = await self._analyse(pending, analysis_id, clock, (MatchClock(p, m), s))
            self._check_open()
            await self.store.put_analysis(doc)
        await self.store.put_storylines(self.match_id, doc["storylines"])
        self.cp["analysis"] = {"id": analysis_id, "horizon": pending["horizon"]}
        scheduled = pending["reason"].startswith("Scheduled") and self.cp["status"] == "live"
        if self.settings.storyline_turns and scheduled:
            self._queue_turn(doc, clock)
        if scheduled:  # a storyline update for the follows, else this minute's recap (queued here, not with it)
            if any(x["lastAnalysisId"] == analysis_id for x in doc["storylines"]):
                self.follow.queue_eval("storylineTurn", pending["ref"], pending["reason"], clock, pending["horizon"],
                                       clock.key)
            else:
                self.follow.queue_eval("scheduled", f"scheduled:{clock.key}", pending["reason"], clock,
                                       pending["horizon"], clock.key)
        self._finish(pending)
        await self._save()
        log.info("%s %s: %d observation(s) accepted, %d sent back once, %d rejected, %d storyline(s) open",
                 self.match_id, pending["ref"], len(doc["observations"]), len(doc.get("retried", [])),
                 len(doc["rejected"]), sum(x["status"] != "resolved" for x in doc["storylines"]))

    async def _analyse(self, pending, analysis_id, clock, horizon):
        previous = await self._storylines(self.cp["analysis"] and self.cp["analysis"]["id"])
        final = pending["ref"].startswith("analysis:fullTime")
        variables, ctx = await self.context.analysis_variables(self.match_id, pending["reason"], horizon,
                                                               pending["seq"], previous)
        info = ctx["info"]
        policy = await self.policy.current()
        rules = policy.analysis
        variables |= grounding.prompt_limits(rules)
        claimed = {}  # claim answers per text, across the repair turn

        async def check(reply):
            accepted, resolves, rejected = validate(reply, ctx["trends"], ctx["ledger"], previous, info, clock,
                                                    rules=rules)
            if reply is None or self.decisions is None:
                return accepted, resolves, rejected
            async with self.decision_slot():
                return await grounding.analyst_claim_rejections(reply, accepted, resolves, rejected, variables,
                                                                self.decisions, policy.claims, claimed)
        retried = []
        if ctx["trends"] or any(x["status"] != "resolved" for x in previous):
            prompt = await self.prompts.pinned("match-analyst", pending["prompt"])
            async def first():
                async with self.gate.slot(self.match_id, "analysis"):
                    return await self.agents.analyse(variables, prompt)
            result = await self._drafted(first, "analyse", prompt.label, variables)
            reply, text, tokens = parse(result.text), result.text, [result.tokens]
            observations, resolves, rejected = await check(reply)
            for _ in range(policy.repair["analyst_turns"]):  # repair turns for what failed
                if not (failed := grounding.repairable(rejected)):
                    break
                retried += failed
                feedback = (text, grounding.repair_request(rejected))

                async def again(feedback=feedback):
                    async with self.gate.slot(self.match_id, "analysis"):
                        return await self.agents.analyse(variables, prompt, feedback=feedback)
                repair = await self._drafted(again, "analyse", prompt.label, variables, feedback)
                reply, text = grounding.merge(reply, rejected, parse(repair.text), rules), repair.text
                tokens.append(repair.tokens)
                observations, resolves, rejected = await check(reply)
            result = AgentResult(result.text, result.model, result.promptVersion, merge_usage(tokens))
        else:  # no trends yet and nothing open: no model call
            result = AgentResult('{"observations": [], "resolve": []}', promptVersion=FIXED_EMPTY)
            observations, resolves, rejected = await check(parse(result.text))
        goals = score(ctx["ledger"], info)
        lines = story.reduce(previous, observations, resolves, ctx["ledger"], match_id=self.match_id,
                             analysis_id=analysis_id, clock=clock, horizon=pending["horizon"], final=final,
                             rules=policy.storylines,
                             final_outcome=f"Full time: {info.home.name} {goals[info.home.id]}-"
                                           f"{goals[info.away.id]} {info.away.name}.")
        return {"id": analysis_id, "matchId": self.match_id, "ref": pending["ref"], "reason": pending["reason"],
                "clock": story.clock_doc(clock, horizon[1]), "horizon": pending["horizon"], "eventSeq": pending["seq"],
                "observations": observations, "resolves": resolves, "rejected": rejected, "retried": retried,
                "storylines": lines, "policyRevision": policy.revision, "model": result.model,
                "promptVersion": result.promptVersion, "tokens": result.tokens, "createdAt": self.now().isoformat()}

    def _queue_turn(self, doc, clock):
        """One storylineTurn step for the most salient storyline this analysis opened or resolved."""
        turned = [x for x in doc["storylines"] if x["lastAnalysisId"] == doc["id"]
                  and (x["status"] == "resolved" or x["openedBy"] == doc["id"])]
        if not turned:
            return
        line = max(turned, key=lambda x: (x["salience"], -x["n"]))
        what = "resolves" if line["status"] == "resolved" else "opens"
        reason = f"Storyline turn at {clock.label}: the analysis {what} the storyline \"{line['label']}\"."
        self._queue(Trigger("storylineTurn", f"turn:{line['id']}:{what}", reason), clock, doc["horizon"],
                    self.active_buckets(), clock.key, turned=line["id"])

    async def _horizon_seq(self, pending):
        """The canonical seq a step reads up to: a key event's own MA3 row (rows later in the same
        second may not have arrived when it was announced), else the latest row up to the horizon."""
        if pending["keyRow"]:
            seq = await self.data.event_seq_of(self.match_id, pending["eventIds"][0])
            if seq is None:  # the notification can overtake the SQL write
                raise EtlBehind(f"{self.match_id}: key event {pending['eventIds'][0]} is not in the ETL yet")
            return seq
        p, m, s = pending["horizon"]
        return await self.data.event_seq(self.match_id, MatchClock(p, m), s)

    async def _period_ends(self, through_period):
        ends = self.cp["periodEnds"]
        for period in range(1, through_period + 1):
            if str(period) not in ends and (end := await self.data.period_end_at(self.match_id, period)):
                ends[str(period)] = end[0].key
                self.cp.setdefault("periodEndSeconds", {})[str(period)] = end[1]
        return {int(p): MatchClock.parse(k) for p, k in ends.items()}

    def _next_minute(self, ends):
        """The next closed minute without a summary, or None."""
        target = self._clock("closedThrough")
        due = minutes_between(self._clock("lastSummarised"), target, ends.get) if target else None
        return due[0] if due else None

    async def _summarise_minute(self, clock, ends):
        period_end = ends.get(clock.periodId) == clock
        await self._summarise(clock, period_end=period_end)
        self.cp["lastSummarised"] = clock.key
        self.cp["minutesSinceStep"] += 1
        # A period's last minute: `_close_periods` merges the whole period and queues its half-time or
        # full-time step, so a compression or scheduled step here would be redone at once. In stoppage
        # time that step is minutes away, so no scheduled step there either.
        if not period_end:
            await self._compress()
        if self.cp["status"] == "live" and not period_end and not stoppage(clock) \
                and (clock.timeMin + 1) % self.settings.analysis_minutes == 0:
            self._queue_analysis(f"analysis:{clock.key}", f"Scheduled analysis at {clock.label}.", clock,
                                 [clock.periodId, clock.timeMin, 59])
        elif self.cp["status"] == "live" and not period_end:  # a minute with an analysis: queued after it
            self.follow.queue_eval("scheduled", f"scheduled:{clock.key}", f"Minute recap at {clock.label}.", clock,
                                   [clock.periodId, clock.timeMin, 59], clock.key)
        if self.cp["status"] == "live":
            self.follow.retry_starts()
        if self.cp["minutesSinceStep"] >= self.settings.fallback_minutes and self.cp["status"] == "live" \
                and not period_end and not stoppage(clock):
            self.cp["minutesSinceStep"] = 0
            reason = f"Scheduled update at {clock.label}: no narrative step in the last " \
                     f"{self.settings.fallback_minutes} minutes."
            self._queue(Trigger("scheduled", f"scheduled:{clock.key}", reason), clock,
                        [clock.periodId, clock.timeMin, 59], self.active_buckets(), clock.key)
        await self._close_periods(ends)
        await self._save()

    def _block_id(self, span):
        return f"block:{self.match_id}:{span.key}"

    async def _summarise(self, clock, period_end=False):
        events = await self.data.events(self.match_id, clock, clock)
        if period_end and not any(e.get("typeId") == 30 for e in events):
            # Closed early by PeriodEnded, but the ETL's SQL rows trail the notification: retry later.
            raise EtlBehind(f"{self.match_id}: the end of period {clock.periodId} is not in the ETL yet")
        if events:
            variables = await self.context.summary_variables(self.match_id, clock, events)
            prompt = await self.prompts.current("minute-summary")
            async with self.gate.slot(self.match_id, "summary"):
                result = await self.agents.summarise(variables, prompt)
        else:
            result = AgentResult(EMPTY_MINUTE, promptVersion=FIXED_EMPTY)
        span = compression.minute(clock)
        await self.store.put_block(ContextBlock(
            self._block_id(span), self.match_id, span.level, clock, clock, result.text, clock, result.model,
            result.promptVersion, result.tokens, self.now().isoformat(), tier=compression.TIERS[span.level]))

    async def _merge(self, merge, tier=None):
        blocks = {b.id: b for b in await self.store.active_blocks(self.match_id)}
        inputs = [blocks[self._block_id(s)] for s in merge.inputs]
        output = merge.output
        if all(b.promptVersion == FIXED_EMPTY for b in inputs):  # nothing happened: nothing to compress
            result = AgentResult(EMPTY_SPAN, promptVersion=FIXED_EMPTY)
        else:
            variables = await self.context.compression_variables(self.match_id, inputs, output.end)
            prompt = await self.prompts.current("context-compression")
            async with self.gate.slot(self.match_id, "summary"):
                result = await self.agents.compress(variables, prompt)
        block = ContextBlock(self._block_id(output), self.match_id, output.level, output.start, output.end,
                             result.text, output.end, result.model, result.promptVersion, result.tokens,
                             self.now().isoformat(), tier=tier or compression.TIERS[output.level])
        await self.store.supersede(block, [b.id for b in inputs])

    async def _spans(self):
        return [compression.Span(b.level, b.coversFrom, b.coversTo) for b in await self.store.active_blocks(self.match_id)]

    async def _compress(self):
        while (merge := compression.next_compression(await self._spans())) is not None:
            await self._merge(merge)

    async def _close_periods(self, ends):
        """Collapse each finished, fully summarised period and queue its narrative step."""
        closed, last = False, self._clock("lastSummarised")
        final = None
        for period, end in sorted(ends.items()):
            if period in self.cp["closedPeriods"] or last is None or last < end:
                continue
            if merge := compression.close_period(await self._spans(), period):
                await self._merge(merge, compression.HALF)
            self.cp["closedPeriods"].append(period)
            self.cp["minutesSinceStep"] = 0
            horizon = [end.periodId, end.timeMin, self.cp.get("periodEndSeconds", {}).get(str(period), 59)]
            final = final or (await self.data.match_info(self.match_id)).periods or self.settings.final_period
            kind = "fullTime" if period >= final else "halfTime"
            self._queue_analysis(f"analysis:{kind}:{period}", "Full time." if period >= final else "Half time.",
                                 end, horizon)
            kind, reason = ("fullTime", "Full time.") if period >= final else ("halfTime", "Half time.")
            self._queue(Trigger(kind, f"{kind}:{period}", reason), end, horizon, self.active_buckets(), end.key)
            self.follow.queue_eval(kind, f"{kind}:{period}", reason, end, horizon, end.key)
            if period >= final:
                self.cp["status"] = "complete"
            closed = True
        return closed

    # --- narrative steps ----------------------------------------------------------

    async def _step(self, trigger, clock, buckets, horizon, prompt, event_seq, analysis_id=None, focus=None):
        if trigger.type != "catchUp":
            self.cp["minutesSinceStep"] = 0
        step_id = f"{self.match_id}:{trigger.ref}"
        shared = {"analysisId": analysis_id, "focus": focus,
                  "story": await self.context.story_variables(self.match_id, horizon, event_seq,
                                                              await self._storylines(analysis_id), focus)}
        info = await self.data.match_info(self.match_id)
        jobs = []
        for target in buckets:
            user_type = target["bucket_id"]
            if existing := await self.store.narrative_for_step(self.match_id, user_type, step_id):
                # Stored but maybe not sent (the publish failed and the step is being retried): send
                # again. Delivery is at least once; the topic and consumers deduplicate on id.
                await self.publisher.publish(existing)
                continue
            variables = await self.context.author_variables(self.match_id, user_type, framing(target, info), trigger,
                                                            horizon, event_seq, shared["story"])
            jobs.append((target, variables))
        results = await self._grounded([v for _, v in jobs], prompt, info, clock,
                                       [f"{step_id} {t['bucket_id']}" for t, _ in jobs])
        for (target, _), result in zip(jobs, results):  # keep what was written, then raise any failure
            if isinstance(result, AgentResult):
                await self._store_narrative(target, result, trigger, step_id, clock, horizon, event_seq, shared)
        if errors := [r for r in results if isinstance(r, BaseException)]:
            raise errors[0]

    async def _store_narrative(self, target, result, trigger, step_id, clock, horizon, event_seq, shared):
        user_type = target["bucket_id"]
        previous = await self.store.narratives(self.match_id, user_type)
        seq = max((n.seq for n in previous), default=0) + 1
        narrative = Narrative(f"narr:{self.match_id}:{user_type}:{seq}", self.match_id, user_type, seq, step_id,
                              trigger, clock, result.text.strip(), result.model, result.promptVersion,
                              result.tokens, self.now().isoformat(), horizon[1], target.get("revision"), event_seq,
                              shared["analysisId"], [shared["focus"]] if shared["focus"] else [])
        self._check_open()
        await self.store.add_narrative(narrative)  # persist before publishing
        await self.publisher.publish(narrative)

    async def _grounded(self, variables_list, prompt, info, clock, labels):
        """Author calls (one per variables) checked by the grounding rules (numbers, names, wording) and the
        decision model's claim questions (the policy's `claims`), with the policy's rewrites. The claim questions of
        every excerpt in a round go in one decision call per evidence state. Per item: an AgentResult, None
        when still ungrounded (dropped), or the exception that failed it."""
        policy = await self.policy.current()

        async def write(variables, feedback=None):
            async def call():
                async with self.author_slots, self.gate.slot(self.match_id, "author"):
                    if feedback is None:
                        return await self.agents.author(variables, prompt)
                    return await self.agents.author(variables, prompt, feedback=feedback)
            return await self._drafted(call, "author", prompt.label, variables, feedback)

        async def check(items):  # [(index, text)] -> {index: reasons}
            reasons = {i: grounding.narrative_reasons(text, variables_list[i], info, clock,
                                                      rules=policy.analysis) for i, text in items}
            if self.decisions is not None and items:
                async with self.decision_slot():
                    claims = await grounding.claim_reasons_many([(text, variables_list[i]) for i, text in items],
                                                                self.decisions, policy.claims)
                for (i, _), found in zip(items, claims):
                    reasons[i] += found
            return reasons

        out = list(await asyncio.gather(*(write(v) for v in variables_list), return_exceptions=True))
        tokens = [[r.tokens] if isinstance(r, AgentResult) else [] for r in out]
        reasons = await check([(i, r.text) for i, r in enumerate(out) if isinstance(r, AgentResult)])
        for _ in range(policy.repair["author_rewrites"]):
            redo = [i for i, found in reasons.items() if found]
            if not redo:
                break
            retries = await asyncio.gather(*(write(variables_list[i], (out[i].text, grounding.narrative_repair_request(
                reasons[i]))) for i in redo), return_exceptions=True)
            for i, retry in zip(redo, retries):
                out[i] = retry
                if isinstance(retry, AgentResult):
                    tokens[i].append(retry.tokens)
                else:
                    reasons.pop(i)
            reasons |= await check([(i, out[i].text) for i in redo if isinstance(out[i], AgentResult)])
        trims = {i: t for i, found in reasons.items() if found and policy.repair["author_trim"]
                 and (t := grounding.trim_unsupported(out[i].text, found))}
        # A kept sentence now reads after a different one ("they" may change team): check the trimmed text whole.
        rechecked = await check(list(trims.items()))
        for i, found in reasons.items():
            trimmed = trims.get(i)
            if trimmed and not rechecked[i]:
                log.warning("%s %s: unsupported sentence(s) removed after %d rewrite(s): %s", self.match_id, labels[i],
                            policy.repair["author_rewrites"], "; ".join(found))
                out[i] = AgentResult(trimmed, out[i].model, out[i].promptVersion, merge_usage(tokens[i]))
            elif found:
                log.warning("%s %s: excerpt dropped, ungrounded after %d rewrite(s): %s", self.match_id, labels[i],
                            policy.repair["author_rewrites"], "; ".join(found))
                out[i] = None
            else:
                out[i] = AgentResult(out[i].text, out[i].model, out[i].promptVersion, merge_usage(tokens[i]))
        return out
