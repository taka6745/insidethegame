"""Application service for a disposable, forward-only event lab.

One process owns one replay. No vendor keys, SQL or HTTP requests belong here.
"""
import asyncio
import logging
from contextlib import suppress
from pydantic import ValidationError

from backend.domain import RuleError
from backend.models.rules import Rule
from backend.services.filter_engine import FilterEngine


class FilterLabService:
    def __init__(self, source, repository, planner, *, local_llm=False):
        self.source, self.repository, self.planner = source, repository, planner
        self.default_source = source
        self.local_llm = local_llm
        self._lock = asyncio.Lock()
        self._plan_lock = asyncio.Lock()
        self._task = None
        self.engine = FilterEngine()
        self.position, self.status, self.error = 0, "ready", None
        self.labels = {}
        self.last_changed = []
        self.run_id = None

    async def initialize(self):
        await asyncio.to_thread(self.repository.initialize, self.source.fingerprint)
        await self._reload()
        # A process restart resumes only when the user explicitly presses Start.
        if self.status == "running":
            self.status = "ready"
            await self._save_progress()

    async def _reload(self):
        run, calculations = await asyncio.to_thread(self.repository.load)
        if run.get("recording_text") is not None:
            self.source = self.default_source.with_recording(run["recording_text"].encode("utf-8"),
                                                           run["recording_filename"])
        if run["source_hash"] != self.source.fingerprint:
            self.run_id, self.position = run["run_id"], run["position"]
            self.error = "The fixture changed. Start a new run before replaying."
            self.status = "error"
            self.engine, self.labels = FilterEngine(), {}
            return
        engine, labels = FilterEngine(), {}
        for event in self.source.history(run["position"]):
            engine.ingest(event)
        for row in calculations:
            result = engine.register(Rule.model_validate(row["rule"]))
            if result.value != row["result"]["value"]:
                raise RuntimeError("Saved calculation differs from replay history")
            engine.restore_version(result.calculation_id, row["result"]["version"])
            labels[result.calculation_id] = row["label"]
        self.run_id, self.position, self.status = run["run_id"], run["position"], run["status"]
        self.engine, self.labels = engine, labels

    def _restore_engine(self, position, previous_versions):
        """Rollback from the known fixture prefix without needing a working DB."""
        engine = FilterEngine()
        for event in self.source.history(position):
            engine.ingest(event)
        for identifier, rule in self.engine.rules.items():
            engine.register(rule)
            engine.restore_version(identifier, previous_versions[identifier])
        self.engine = engine

    async def _save_progress(self, results=()):
        await asyncio.to_thread(self.repository.progress, self.run_id, self.position, self.status,
                                [result.model_dump(mode="json") for result in results])

    async def close(self):
        # Wait for an in-flight write before cancellation: cancelling to_thread
        # does not stop its database thread. start/reset use this same lock.
        async with self._lock:
            task, self._task = self._task, None
            if task:
                task.cancel()
        if task:
            with suppress(asyncio.CancelledError):
                await task

    def scenario(self):
        return self.source.describe()

    async def recording(self):
        async with self._lock:
            return self.source.filename, self.source.content

    async def event_record(self, delivery_index):
        async with self._lock:
            if delivery_index < 0 or delivery_index >= self.position or self.status == "error":
                raise RuleError("event_not_received", "This event has not been received in the current run", 404)
            return self.source.inspect(delivery_index)

    async def load_recording(self, content=None, filename=None):
        try:
            source = self.default_source if content is None else self.source.with_recording(content, filename)
        except ValidationError as exc:
            error = exc.errors(include_input=False, include_context=False)[0]
            raise RuleError("invalid_recording", f"Invalid recording: {error['msg']}", 422) from None
        except (ValueError, UnicodeError):
            raise RuleError("invalid_recording", "Use a valid UTF-8 synthetic match JSON recording", 422) from None
        async with self._lock:
            if self.status == "running" or self._plan_lock.locked():
                raise RuleError("recording_busy", "Wait for the replay or rule request to finish before loading a recording", 409)
            run_id = await asyncio.to_thread(self.repository.replace_recording, source.fingerprint,
                                            source.content if content is not None else None,
                                            source.filename if content is not None else None)
            self.source, self.run_id = source, run_id
            self.engine, self.labels, self.last_changed = FilterEngine(), {}, []
            self.position, self.status, self.error = 0, "ready", None
            self._task = None
            scenario = self.scenario()
        return {"scenario": scenario, "state": await self.state()}

    def _calculation(self, result):
        return {"id": result.calculation_id, "label": self.labels[result.calculation_id],
                "value": result.value, "version": result.version,
                "rule": self.engine.rule(result.calculation_id).model_dump(mode="json")}

    async def state(self):
        async with self._lock:
            return {"synthetic": True, "run_id": self.run_id, "match_id": self.source.match_id,
                    "status": self.status, "position": self.position, "total": len(self.source.events),
                    "error": self.error,
                    "events": [self.source.display_delivery(i) for i in range(max(0, self.position - 100), self.position)],
                    "calculations": [self._calculation(r) for r in self.engine.calculations],
                    "changed_ids": self.last_changed,
                    "metrics": {"total_rules": self.engine.count,
                                "candidate_count": self.engine.last_candidate_count,
                                "index_probe_count": self.engine.last_index_probe_count,
                                "changed_count": len(self.last_changed)},
                    "llm": {"configured": self.local_llm, "mode": "local" if self.local_llm else "fixture"}}

    async def register(self, rule, label):
        async with self._lock:
            if rule.match_id != self.source.match_id:
                raise RuleError("wrong_match", "Choose the current lab match", 422)
            if self.status == "error":
                raise RuleError("reset_required", "Start a new run first")
            # Calculate a new rule against observed history without publishing it
            # into live memory before persistence succeeds.
            identifier = rule.calculation_id
            if identifier in self.labels:
                result = self.engine.get(identifier)
            else:
                result = FilterEngine().register(rule, self.source.history(self.position))
            await asyncio.to_thread(self.repository.register, self.run_id, label,
                                    rule.model_dump(mode="json"), result.model_dump(mode="json"))
            self.engine.register(rule)
            self.labels.setdefault(result.calculation_id, label)
            return self._calculation(result)

    async def plan(self, prompt):
        # Model calls are off the event-processing lock; replay stays responsive.
        if self._plan_lock.locked():
            raise RuleError("planner_busy", "Wait for the current rule request to finish", 409)
        async with self._plan_lock:
            # Wait for any recording swap to commit before capturing its context.
            async with self._lock:
                description = self.source.describe()
                context = {key: description[key] for key in ("match_id", "players", "teams")}
                context["standard_stats"] = []
            outcome = await self.planner.plan(prompt, context)
            return outcome.model_dump(mode="json")

    async def start(self, interval_ms):
        async with self._lock:
            if self.status == "running":
                raise RuleError("already_running", "Replay is already running")
            if self.position >= len(self.source.events) or self.status == "error":
                raise RuleError("reset_required", "Start a new run before replaying")
            previous = self.status, self.error
            self.status, self.error = "running", None
            try:
                await self._save_progress()
            except Exception:
                self.status, self.error = previous
                raise
            self._task = asyncio.create_task(self._run(interval_ms / 1000))
        return await self.state()

    async def _run(self, interval):
        try:
            while True:
                await asyncio.sleep(interval)
                if not await self.advance():
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            # No raw provider/DB exception text or credentials in the UI.
            logging.getLogger(__name__).exception("Filter replay failed")
            self.error = "Replay stopped. Check the backend logs and start a new run."
            self.status = "error"

    async def advance(self):
        """One forward event. Also used by deterministic integration tests."""
        async with self._lock:
            event = self.source.next_event(self.position)
            if event is None:
                return False
            previous_position, previous_status = self.position, self.status
            changed = self.engine.ingest(event)
            self.position += 1
            if self.position == len(self.source.events):
                self.status = "finished"
            try:
                await self._save_progress(changed)
            except Exception:
                changed_ids = {result.calculation_id for result in changed}
                versions = {result.calculation_id: result.version - (result.calculation_id in changed_ids)
                            for result in self.engine.calculations}
                self._restore_engine(previous_position, versions)
                self.position, self.status = previous_position, previous_status
                raise
            self.last_changed = [r.calculation_id for r in changed]
            return self.status != "finished"

    async def reset(self):
        async with self._lock:
            # Capture/cancel the task only after any concurrent start has finished
            # creating it, and after any in-flight event transaction has finished.
            task, self._task = self._task, None
            if task:
                task.cancel()
            try:
                await asyncio.to_thread(self.repository.reset, self.source.fingerprint)
                await self._reload()
                self.error, self.last_changed = None, []
            except Exception:
                self.status = "error"
                self.error = "The new run could not be loaded. Try starting a new run again."
                raise
            finally:
                if task:
                    with suppress(asyncio.CancelledError):
                        await task
        return await self.state()
