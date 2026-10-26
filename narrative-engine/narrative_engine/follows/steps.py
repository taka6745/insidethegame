"""Story follows inside a match's orchestrator: read the followed topics, queue and run `subscriptionEval` and
`subscriptionStart` steps (README.md, Follows). A decision is stored before its fired topics are pinned,
so a restart or backlog never asks again; a `FollowClip` is sent apart from the narratives."""
import copy
import logging

from narrative_engine.agents.prompt_source import render_template
from narrative_engine.audience.targets import framing
from narrative_engine.context.render import score
from narrative_engine.core.models import AgentResult, MatchClock, Narrative, Trigger
from narrative_engine.follows import pipeline

log = logging.getLogger(__name__)
SCORE_CHANGES = ("Goal", "OwnGoal", "VarOverturn")  # key types render.score counts
PREFILTER = {"keyEvent": "key_events", "scheduled": "minute_recaps", "storylineTurn": "storyline_updates"}


def before(narrative, horizon):
    return (narrative.matchTime.periodId, narrative.matchTime.timeMin, narrative.timeSec or 0) < tuple(horizon)


class FollowSteps:
    def __init__(self, engine, topics, decisions):
        self.e, self.topics, self.decisions = engine, topics, decisions

    @property
    def enabled(self):
        return self.topics is not None and self.decisions is not None

    @property
    def cp(self):
        return self.e.cp

    async def sync(self):
        """Read the followed topics; True if they changed. A (topic, bucket) pair new since the last read
        gets a "story so far" step. The served `clips` settings are kept apart (`cp["clips"]`): the shared key-event
        clips (orchestrator `MomentClip`) read them without a decision model or any follow."""
        if self.topics is None:
            return False
        try:
            targets = await self.topics.current(self.e.match_id)
        except Exception as error:  # keep the last known topics; the poll tries again
            log.warning("%s: subscription targets unavailable (%s)", self.e.match_id, type(error).__name__)
            return False
        self.cp["clips"] = targets.config["clips"]
        if not self.enabled:
            return False
        previous = self.cp.get("follows")
        if previous and (previous["revision"], previous["configRevision"]) == (targets.revision,
                                                                                targets.config_revision):
            return False
        self.cp["follows"] = {"revision": targets.revision, "configRevision": targets.config_revision,
                              "config": targets.config, "topics": [dict(t) for t in targets.topics]}
        seen = set(self.cp.get("followPairs") or [])
        pairs = {f"{t['topic_id']}|{b}": (t, b) for t in targets.topics for b in t["buckets"]}
        if previous is not None and self.cp["status"] == "live" and self.cp["horizon"] is not None:
            for pair in sorted(set(pairs) - seen):
                self._queue_start(*pairs[pair])
        self.cp["followPairs"] = sorted(seen | set(pairs))
        return True

    def _queue_start(self, topic, bucket, attempt=0):
        target = next((t for t in self.e.active_buckets() or [] if t["bucket_id"] == bucket), None)
        if target is None:  # a bucket the audience config has disabled: nothing is written for it
            return
        p, m, _ = self.cp["horizon"]
        ref = f"catchUp:{bucket}"
        reason = self.cp["follows"]["config"]["catch_up"]["reason"]  # served tunable (subscriptions.catch_up)
        self.e._queue(Trigger("subscriptionStart", f"sub:start:{topic['topic_id']}:{bucket}"
                              + (f":retry{attempt}" if attempt else ""), reason),
                      MatchClock(p, m), self.cp["horizon"], [target], self.cp["closedThrough"],
                      triggerType="catchUp", triggerRef=ref, topics=[copy.deepcopy(topic)],
                      follow=copy.deepcopy(self.cp["follows"]["config"]),
                      followRevision=self.cp["follows"]["configRevision"], attempt=attempt)

    def retry_starts(self):
        """Queue again, at the current horizon, each "story so far" that was dropped as ungrounded before it
        (`catch_up.retries` attempts; a later horizon gives the author more to cite). Called as minutes close."""
        retries, follows = self.cp.get("followRetries") or [], self.cp.get("follows")
        if not retries or not follows or self.cp["horizon"] is None:
            return
        topics = {t["topic_id"]: t for t in follows["topics"]}
        waiting = []
        for r in retries:
            topic = topics.get(r["topicId"])
            if topic is None or r["bucket"] not in topic["buckets"]:
                continue  # unfollowed since: nothing to catch up
            if tuple(self.cp["horizon"]) <= tuple(r["after"]):
                waiting.append(r)
                continue
            self._queue_start(topic, r["bucket"], r["attempt"])
        self.cp["followRetries"] = waiting

    def queue_eval(self, trigger_type, trigger_ref, reason, clock, horizon, after, key_row=None, event_ids=()):
        """Queue a follow evaluation for this update, if anything is followed and the prefilter allows it."""
        follows = self.cp.get("follows")
        if not self.enabled or not follows or not any(t["buckets"] for t in follows["topics"]):
            return
        flag = PREFILTER.get(trigger_type)
        if flag and not follows["config"]["prefilter"].get(flag, True):
            return
        self.e._queue(Trigger("subscriptionEval", f"sub:{trigger_ref}", reason, tuple(event_ids)), clock, horizon,
                      self.e.active_buckets(), after, key_row, triggerType=trigger_type, triggerRef=trigger_ref,
                      topics=copy.deepcopy(follows["topics"]), follow=copy.deepcopy(follows["config"]),
                      followRevision=follows["configRevision"])

    async def run(self, pending):
        e = self.e
        if pending["buckets"] is None:
            pending["buckets"] = await e._buckets_now()
        if "seq" not in pending:  # pinned on the first attempt
            pending["seq"] = await e._horizon_seq(pending)
            pending["analysisId"] = e.cp["analysis"] and e.cp["analysis"]["id"]
            pending["authorPrompt"] = (await e.prompts.current("subscription-author")).label
            if pending["type"] == "subscriptionEval":
                pending["prompt"] = (await e.prompts.current("subscription-decision")).label
            await e._save()
        info = await e.data.match_info(e.match_id)
        update = await self._update(pending, info)
        if pending["type"] == "subscriptionStart":
            fired = {pending["topics"][0]["topic_id"]: None}
        else:
            if "fired" not in pending:
                await self._pin_decision(pending, info, update)
            fired = pending["fired"]
            await self._publish_clips(pending, fired)
        topics = {t["topic_id"]: t for t in pending["topics"]}
        targets = {t["bucket_id"]: t for t in pending["buckets"]}
        jobs = [(topics[topic_id], targets[b], verdict) for topic_id, verdict in fired.items()
                for b in topics[topic_id]["buckets"] if b in targets]
        written, dropped = await self._write(pending, info, update, jobs)
        attempt = pending.get("attempt", 0)
        if pending["type"] == "subscriptionStart" and dropped and attempt < pending["follow"]["catch_up"]["retries"]:
            topic = pending["topics"][0]
            e.cp.setdefault("followRetries", []).extend(
                {"topicId": topic["topic_id"], "bucket": b, "attempt": attempt + 1, "after": pending["horizon"]}
                for b in dropped)
        e._finish(pending)
        await e._save()
        log.info("%s %s: %d topic(s) fired, %d follow narrative(s)", e.match_id, pending["ref"], len(fired), written)

    async def _pin_decision(self, pending, info, update):
        e = self.e
        decision_id = f"subdec:{e.match_id}:{pending['triggerRef']}"
        doc = await e.store.get_decision(e.match_id, decision_id)
        if doc is None:  # asked once: a retry or restart reuses the stored answer
            doc = await self._decide(pending, info, update, decision_id)
            e._check_open()
            await e.store.put_decision(doc)
        pending["fired"] = {t: {k: doc["verdicts"][t][k] for k in ("score", "confidence", "novelty")}
                           | {"clip": bool(doc["verdicts"][t].get("clip")), "model": doc["model"]}
                           for t in doc["fired"]}
        fired_log = e.cp.setdefault("followFired", {})
        for topic_id in doc["fired"]:
            fired_log[topic_id] = {"horizon": pending["horizon"], "ref": pending["triggerRef"]}
        await e._save()

    async def _publish_clips(self, pending, fired):
        """Each fired topic's moment clip (a `clip` verdict on a key event), sent on its own: the clip is a fact
        about the moment, so a follow narrative dropped as ungrounded never loses it. Sent on every attempt (at
        least once; the backend keeps one per topic and moment)."""
        e = self.e
        if pending["triggerType"] != "keyEvent" or not pending["eventIds"]:
            return
        for topic_id, verdict in fired.items():
            if verdict and verdict.get("clip"):
                e._check_open()
                await e.publisher.publish_clip({
                    "type": "FollowClip", "id": f"clip:{e.match_id}:{topic_id}:{pending['eventIds'][0]}",
                    "matchId": e.match_id, "topicId": topic_id, "eventId": pending["eventIds"][0],
                    "eventSeq": pending["seq"], "stepId": f"{e.match_id}:sub:{topic_id}:{pending['triggerRef']}",
                    "decision": verdict})

    async def _decide(self, pending, info, update, decision_id):
        e = self.e
        clock = MatchClock.parse(pending["clock"])
        lines = await e._storylines(pending["analysisId"])
        by_id = {s["id"]: s for s in lines}
        key_row = pending["keyRow"] and {**pending["keyRow"], "id": pending["eventIds"][0]}
        events = await e.data.events(e.match_id, clock, clock) if pending["triggerType"] == "scheduled" else ()
        moved = [s for s in lines if s.get("lastAnalysisId") == pending["analysisId"]]
        entities = pipeline.update_entities(pending["triggerType"], info, key_row, events, moved)
        config, limits = pending["follow"], pending["follow"]["limits"]
        clip = pipeline.clip_moment(pending["triggerType"], key_row, config)
        fired_log = e.cp.get("followFired") or {}
        candidates, skipped = [], {}
        for topic in pending["topics"]:
            if not topic["buckets"] or not pipeline.is_candidate(topic, entities, by_id, pending["seq"]):
                continue
            last = fired_log.get(topic["topic_id"])
            if pipeline.within_gap(last and last["horizon"], pending["horizon"], limits) \
                    and not (clip or pipeline.pivotal(pending["triggerType"], key_row, limits)):  # never skip a clip
                skipped[topic["topic_id"]] = "gap"
                continue
            candidates.append(topic)
        doc = {"id": decision_id, "matchId": e.match_id, "ref": pending["triggerRef"],
               "triggerType": pending["triggerType"], "horizon": pending["horizon"], "eventSeq": pending["seq"],
               "analysisId": pending["analysisId"], "configRevision": pending["followRevision"],
               "candidates": [t["topic_id"] for t in candidates],
               "skipped": skipped, "verdicts": {}, "fired": [], "questions": 0, "model": None, "tokens": None,
               "promptVersion": None, "createdAt": e.now().isoformat()}
        if not candidates:
            return doc
        if pipeline.wrap_up(pending["triggerType"], limits):
            verdicts = {t["topic_id"]: {"score": None, "confidence": None, "novelty": None, "fired": True,
                                        "wrapUp": True} for t in candidates}
            return {**doc, "verdicts": verdicts, "fired": list(verdicts)}
        p, m, s = pending["horizon"]
        horizon = (MatchClock(p, m), s)
        last_texts = {t["topic_id"]: await self._last_text(t["topic_id"], pending["horizon"]) for t in candidates}
        variables = await e.context.follow_variables(e.match_id, horizon, pending["seq"], lines)
        # The shared state carries no viewer text (no labels or focus): that lives only in each topic's questions.
        variables |= {"update": update, "narrative_excerpts": await self._recent_insights(pending["horizon"])}
        prompt = await e.prompts.pinned("subscription-decision", pending["prompt"])
        asked, keys = pipeline.questions(candidates, config, last_texts, info, by_id, clip)
        async with e.decision_slot():
            result = await self.decisions.decide(render_template(prompt, variables), asked)
        verdicts = pipeline.verdicts(candidates, result.answers, keys, config, clip)
        fired = [t["topic_id"] for t in candidates if verdicts[t["topic_id"]]["fired"]]
        return {**doc, "verdicts": verdicts, "fired": fired, "questions": len(asked), "model": result.model,
                "tokens": result.tokens, "promptVersion": prompt.label}

    async def _write(self, pending, info, update, jobs):
        """The fired topics' narratives, one per (topic, bucket) not yet written: drafted together, so their
        claim checks share decision calls. Returns how many were written and the buckets of those dropped as
        ungrounded; raises a failure after storing the rest."""
        e = self.e
        clock = MatchClock.parse(pending["clock"])
        p, m, s = pending["horizon"]
        horizon = (MatchClock(p, m), s)
        lines = await e._storylines(pending["analysisId"])
        by_id = {x["id"]: x for x in lines}
        trigger = Trigger(pending["triggerType"], pending["triggerRef"], update, tuple(pending["eventIds"]))
        todo = []
        for topic, target, verdict in jobs:
            topic_id, user_type, spec = topic["topic_id"], target["bucket_id"], topic["spec"]
            step_id = f"{e.match_id}:sub:{topic_id}:{pending['triggerRef']}"
            if existing := await e.store.subscription_narrative_for_step(e.match_id, topic_id, user_type, step_id):
                await e.publisher.publish(existing)  # stored but maybe not sent: send again (at least once)
                continue
            focus = spec.get("storyline_id") if spec["kind"] == "storyline" and spec.get("storyline_id") in by_id \
                else None
            story = await e.context.story_variables(e.match_id, horizon, pending["seq"], lines, focus)
            variables = await e.context.author_variables(e.match_id, user_type, framing(target, info), trigger,
                                                         horizon, pending["seq"], story, before=pending["horizon"])
            previous = [n for n in await e.store.subscription_narratives(e.match_id, topic_id, user_type)
                        if before(n, pending["horizon"])]
            variables |= {"follow": pipeline.describe(spec, info, by_id),
                          "story_so_far": "\n".join(f"- {n.matchTime.label} {n.text}" for n in previous)
                          or "Nothing yet."}
            todo.append((topic_id, target, verdict, step_id, focus, variables))
        prompt = await e.prompts.pinned("subscription-author", pending["authorPrompt"])
        results = await e._grounded([t[-1] for t in todo], prompt, info, clock,
                                    [f"{t[3]} {t[1]['bucket_id']}" for t in todo])
        written, dropped = 0, []
        for (topic_id, target, verdict, step_id, focus, _), result in zip(todo, results):
            if result is None:
                dropped.append(target["bucket_id"])
            if not isinstance(result, AgentResult):
                continue
            user_type = target["bucket_id"]
            seq = max((n.seq for n in await e.store.subscription_narratives(e.match_id, topic_id, user_type)),
                      default=0) + 1
            narrative = Narrative(
                f"sub:{e.match_id}:{topic_id}:{user_type}:{seq}", e.match_id, user_type, seq, step_id, trigger, clock,
                result.text.strip(), result.model, result.promptVersion, result.tokens, e.now().isoformat(), s,
                target.get("revision"), pending["seq"], pending["analysisId"], [focus] if focus else [],
                kind="subscription", topicId=topic_id, decision=verdict)
            e._check_open()
            await e.store.add_subscription_narrative(narrative)  # persist before publishing
            await e.publisher.publish(narrative)
            written += 1
        if errors := [r for r in results if isinstance(r, BaseException)]:
            raise errors[0]
        return written, dropped

    async def _update(self, pending, info):
        """The update being judged, in words: the key event, the minute's recap, what the analysis moved, or
        the period end."""
        e = self.e
        clock = MatchClock.parse(pending["clock"])
        kind = pending["triggerType"]
        if kind == "keyEvent":
            return e._key_reason(pending, info) + await self._score_change(pending, info)
        if kind == "catchUp":
            return pending["reason"]
        if kind == "storylineTurn":
            lines = [s for s in await e._storylines(pending["analysisId"])
                     if s.get("lastAnalysisId") == pending["analysisId"]]
            out = [f"Match analysis at {clock.label}."]
            for s in lines:
                if s["status"] == "resolved":
                    out.append(f"- Storyline \"{s['label']}\" resolved: {s.get('outcome') or ''}".rstrip())
                elif s["beats"] and s["beats"][-1]["analysisId"] == pending["analysisId"]:
                    what = "opened" if s.get("openedBy") == pending["analysisId"] else "developed"
                    out.append(f"- Storyline \"{s['label']}\" {what}: {s['beats'][-1]['headline']}")
            return "\n".join(out) if len(out) > 1 else out[0] + " No storyline moved."
        recap = next((b.summary for b in await e.store.all_blocks(e.match_id)
                      if b.level == 0 and b.coversFrom == b.coversTo == clock), None)
        head = f"Minute recap at {clock.label}" if kind == "scheduled" else pending["reason"].rstrip(".") + \
            f" at {clock.label}"
        return f"{head}: {recap}" if recap else f"{head}."

    async def _score_change(self, pending, info):
        """For a key event that changes the score: the score before and after it, from ETL's key-event ledger at
        the horizon ("" for any other event, or while the ledger does not have this one yet)."""
        if pending["keyRow"]["keyType"] not in SCORE_CHANGES:
            return ""
        p, m, s = pending["horizon"]
        rows = sorted(await self.e.data.key_events(self.e.match_id, MatchClock(p, m), s),
                      key=lambda r: (r["periodId"], r["timeMin"], r["timeSec"]))
        at = next((i for i, r in enumerate(rows) if str(r["id"]) == str(pending["eventIds"][0])), None)
        if at is None:
            return ""
        line = lambda goals: f"{info.home.name} {goals[info.home.id]}-{goals[info.away.id]} {info.away.name}"
        return f". Score before: {line(score(rows[:at], info))}; score now: {line(score(rows[:at + 1], info))}"

    async def _last_text(self, topic_id, horizon):
        """The topic's latest narrative before `horizon` (its first bucket's version), or None."""
        found = [n for n in await self.e.store.subscription_narratives(self.e.match_id, topic_id) if before(n, horizon)]
        if not found:
            return None
        latest = max(found, key=lambda n: (n.matchTime, n.timeSec or 0, n.stepId))
        return min((n for n in found if n.stepId == latest.stepId), key=lambda n: n.userType).text

    async def _recent_insights(self, horizon):
        """The match's latest insights before `horizon`: one version (the first bucket's) per step."""
        steps = {}
        for n in await self.e.store.narratives(self.e.match_id):
            if before(n, horizon) and (n.stepId not in steps or n.userType < steps[n.stepId].userType):
                steps[n.stepId] = n
        latest = sorted(steps.values(), key=lambda n: (n.matchTime, n.timeSec or 0, n.stepId))[-self.e.context.last_n:]
        return "\n".join(f"- {n.matchTime.label} {n.text}" for n in latest) or "None yet."
