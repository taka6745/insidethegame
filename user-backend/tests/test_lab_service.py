"""Failure recovery and lifecycle tests without HTTP, PostgreSQL or models."""
import asyncio
from copy import deepcopy
from threading import Event as ThreadEvent

import pytest
from pydantic import BaseModel

from backend.adapters.replay_source import FixtureEventSource
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
        assert await service.plan("Track corners") == {"status": "clarification"}
        assert set(planner.context) == {"match_id", "players", "teams", "standard_stats"}
        assert planner.context["standard_stats"] == []
    asyncio.run(run())
