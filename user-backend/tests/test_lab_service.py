"""Failure recovery and lifecycle tests without HTTP, PostgreSQL or models."""
import asyncio
import json
from copy import deepcopy
from threading import Event as ThreadEvent

import pytest
from pydantic import BaseModel

from backend.adapters.replay_source import FixtureEventSource
from backend.domain import RuleError
from backend.models.rules import Rule
from backend.services.lab import FilterLabService


class MemoryRepository:
    def __init__(self):
        self.run = None
        self.rows = {}
        self.load_calls = 0
        self.fail_load = self.fail_progress = self.fail_register = False
        self.block_progress = False
        self.entered, self.release = ThreadEvent(), ThreadEvent()

    def initialize(self, fingerprint):
        if self.run is None:
            self.reset(fingerprint)

    def reset(self, fingerprint):
        sequence = 1 if self.run is None else int(self.run["run_id"]) + 1
        self.run = {"run_id": str(sequence), "position": 0, "status": "ready", "source_hash": fingerprint}
        self.rows = {}

    def load(self):
        self.load_calls += 1
        if self.fail_load:
            raise OSError("Database unavailable")
        return deepcopy(self.run), deepcopy(list(self.rows.values()))

    def register(self, run_id, label, rule, result):
        if self.fail_register:
            raise OSError("Database unavailable")
        assert self.run["run_id"] == run_id
        self.rows.setdefault(result["calculation_id"], {"label": label, "rule": rule, "result": result})

    def progress(self, run_id, position, status, results):
        if self.block_progress:
            self.block_progress = False
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError("Test did not release the database operation")
        if self.fail_progress:
            raise OSError("Database unavailable")
        assert self.run["run_id"] == run_id
        self.run.update(position=position, status=status)
        for result in results:
            self.rows[result["calculation_id"]]["result"] = result


async def setup(service_type=FilterLabService, planner=None):
    repository = MemoryRepository()
    service = service_type(FixtureEventSource(), repository, planner)
    await service.initialize()
    return service, repository


def test_planner_waits_for_recording_commit_before_defining_goal():
    class Outcome(BaseModel):
        team: str

    class Planner:
        async def plan(self, prompt, context):
            return Outcome(team=context["teams"][0]["name"])

    async def run():
        service, repository = await setup(planner=Planner())
        def replace(fingerprint, content, filename):
            repository.entered.set()
            assert repository.release.wait(3)
            repository.reset(fingerprint)
            return repository.run["run_id"]
        repository.replace_recording = replace
        recording = deepcopy(service.source.spec)
        recording["teams"][0]["name"] = "New recording team"
        load = asyncio.create_task(service.load_recording(json.dumps(recording).encode(), "new.json"))
        assert await asyncio.to_thread(repository.entered.wait, 1)
        plan = asyncio.create_task(service.plan("Track headers"))
        await asyncio.sleep(0)
        repository.release.set()
        await load
        assert (await plan)["team"] == "New recording team"
    asyncio.run(run())


def test_failed_start_restores_status_and_can_be_retried():
    async def run():
        service, repository = await setup()
        repository.fail_progress = repository.fail_load = True
        with pytest.raises(OSError):
            await service.start(5000)
        assert (await service.state())["status"] == "ready"
        assert service._task is None
        repository.fail_progress = repository.fail_load = False
        assert (await service.start(5000))["status"] == "running"
        await service.close()
    asyncio.run(run())


def test_failed_registration_keeps_readable_committed_state_when_db_reads_also_fail():
    async def run():
        service, repository = await setup()
        before = await service.state()
        load_calls = repository.load_calls
        repository.fail_register = repository.fail_load = True
        with pytest.raises(OSError):
            await service.register(Rule(match_id=service.source.match_id), "All actions")
        assert await service.state() == before
        assert repository.load_calls == load_calls
    asyncio.run(run())


def test_failed_event_transaction_rolls_back_values_position_versions_without_db_reads():
    async def run():
        service, repository = await setup()
        calculation = await service.register(Rule(match_id=service.source.match_id), "All actions")
        await service.advance()
        before = await service.state()
        assert before["calculations"][0]["value"] == 1
        load_calls = repository.load_calls
        repository.fail_progress = repository.fail_load = True
        with pytest.raises(OSError):
            await service.advance()
        after = await service.state()
        for key in ("position", "status", "events", "calculations", "changed_ids"):
            assert after[key] == before[key]
        assert repository.load_calls == load_calls
        repository.fail_progress = repository.fail_load = False
        await service.advance()
        result = service.engine.get(calculation["id"])
        assert (result.value, result.version) == (2, 3)
    asyncio.run(run())


def test_reset_serializes_with_start_persistence_and_cancels_newly_created_task():
    class ControlledReplay(FilterLabService):
        async def _run(self, interval):
            await self.gate.wait()
            await self.advance()

    async def run():
        service, repository = await setup(ControlledReplay)
        service.gate = asyncio.Event()
        repository.block_progress = True
        starting = asyncio.create_task(service.start(50))
        assert await asyncio.to_thread(repository.entered.wait, 2)
        resetting = asyncio.create_task(service.reset())
        await asyncio.sleep(0)  # Reset reaches the lifecycle lock while Start waits.
        repository.release.set()
        await starting
        reset_state = await resetting
        assert reset_state["position"] == 0
        assert reset_state["status"] == "ready"
        assert service._task is None
        service.gate.set()
        await asyncio.sleep(0)
        assert (await service.state())["position"] == 0
    asyncio.run(run())


def test_close_waits_for_in_flight_database_write_before_stopping_replay():
    async def run():
        service, repository = await setup()
        repository.block_progress = True
        advancing = asyncio.create_task(service.advance())
        assert await asyncio.to_thread(repository.entered.wait, 2)
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0)
        assert not closing.done()
        repository.release.set()
        await advancing
        await closing
        assert repository.run["position"] == service.position == 1
    asyncio.run(run())


def test_reset_load_failure_blocks_further_replay_until_retry():
    async def run():
        service, repository = await setup()
        repository.fail_load = True
        with pytest.raises(OSError):
            await service.reset()
        state = await service.state()
        assert state["status"] == "error"
        assert state["error"]
        repository.fail_load = False
        assert (await service.reset())["status"] == "ready"
    asyncio.run(run())


def test_restart_restores_versions_and_only_exposes_observed_events():
    async def run():
        service, repository = await setup()
        calculation = await service.register(Rule(match_id=service.source.match_id), "All actions")
        await service.advance()
        await service.advance()
        restored = FilterLabService(service.source, repository, None)
        await restored.initialize()
        state = await restored.state()
        assert len(state["events"]) == state["position"] == 2
        assert restored.engine.get(calculation["id"]) == service.engine.get(calculation["id"])
    asyncio.run(run())


def test_decimal_measurements_and_corrections_restore_after_restart():
    async def run():
        service, repository = await setup()
        first = service.source.events[0].model_copy(update={"distance_metres": 0.1})
        second = service.source.events[1].model_copy(update={"distance_metres": 0.2})
        correction = second.model_copy(update={"revision": 2, "distance_metres": 0.3})
        service.source.events = (first, second, correction)
        calculation = await service.register(Rule(match_id=service.source.match_id, operation="sum", sum_field="distance_metres"), "Distance")
        for _ in service.source.events:
            await service.advance()
        assert service.engine.get(calculation["id"]).value == 0.4
        restored = FilterLabService(service.source, repository, None)
        await restored.initialize()
        assert restored.engine.get(calculation["id"]) == service.engine.get(calculation["id"])
    asyncio.run(run())


def test_planner_receives_entity_catalogue_not_future_events_or_preset_answers():
    class Outcome(BaseModel):
        status: str = "clarification"

    class Planner:
        async def plan(self, prompt, context):
            self.prompt, self.context = prompt, context
            return Outcome()

    async def run():
        planner = Planner()
        service, _ = await setup(planner=planner)
        outcome = await service.plan("Track corners")
        assert outcome["status"] == "clarification" and outcome["conversation_id"]
        assert set(planner.context) == {"match_id", "players", "teams", "standard_stats"}
        assert planner.context["standard_stats"] == []
    asyncio.run(run())


def test_clarification_keeps_original_request_and_server_question():
    from backend.agents.models import PlanOutcome

    class Planner:
        async def plan(self, prompt, context, history=None):
            self.history = history
            return PlanOutcome(status="clarification", source="fixture", message="Which player?")

    async def run():
        planner = Planner()
        service, _ = await setup(planner=planner)
        first = await service.plan("Track headed shots after minute 60")
        second = await service.plan("Mbappe", first["conversation_id"])
        assert second["conversation_id"] == first["conversation_id"]
        assert planner.history == [
            {"role": "user", "content": "Track headed shots after minute 60"},
            {"role": "assistant", "content": "Which player?"},
        ]
        await service.reset()
        with pytest.raises(RuleError, match="expired"):
            await service.plan("Mbappe", first["conversation_id"])
    asyncio.run(run())


def test_reset_during_model_call_discards_stale_plan():
    from backend.agents.models import PlanOutcome
    from backend.domain import RuleError

    class Planner:
        async def plan(self, prompt, context):
            started.set()
            await release.wait()
            return PlanOutcome(status="clarification", source="fixture", message="Which player?")

    async def run():
        nonlocal started, release
        started, release = asyncio.Event(), asyncio.Event()
        service, _ = await setup(planner=Planner())
        planning = asyncio.create_task(service.plan("Track headers"))
        await started.wait()
        await service.reset()
        release.set()
        with pytest.raises(RuleError, match="changed"):
            await planning
    started = release = None
    asyncio.run(run())


def test_clarification_options_are_preserved_for_ordinal_answers():
    from backend.agents.models import Clarification, PlanOutcome

    class Planner:
        async def plan(self, prompt, context, history=None):
            self.history = history
            return PlanOutcome(status="clarification", source="fixture", clarification=Clarification(
                question="Which player?", options=["Mbappe", "Palmer", "Colwill"], missing_fields=["player"]))

    async def run():
        planner = Planner()
        service, _ = await setup(planner=planner)
        first = await service.plan("Track his headers")
        await service.plan("The second one", first["conversation_id"])
        assert planner.history[1]["content"] == "Which player?\nOptions:\n1. Mbappe\n2. Palmer\n3. Colwill"
    asyncio.run(run())
