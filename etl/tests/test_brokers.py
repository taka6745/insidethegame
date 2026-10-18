"""Broker delivery ordering, retry and HTTP-mode separation."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from demo_etl.adapters.brokers import BrokerRuntime, MatchEventHandler
from demo_etl.routes.http import create_app
from demo_etl.services.match import MatchService
from test_etl import MemoryHistory, MemoryStats, payload, recording


class Partition:
    def __init__(self): self.checkpoints = []
    async def update_checkpoint(self, event): self.checkpoints.append(event)


class Publisher:
    def __init__(self, service):
        self.service = service
        self.calls = 0
        self.messages = []
        self.fail_once = False

    async def publish(self, snapshot):
        self.calls += 1
        # Notification must never precede readable history and stats.
        self.service.payload(snapshot.snapshot.id)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError('Temporary broker outage')
        self.messages.append(snapshot)


@pytest.fixture
def setup(tmp_path):
    service = MatchService(MemoryHistory(), MemoryStats(), recording(tmp_path))
    data = payload()
    data.snapshot.recording_hash = service.recording.fingerprint
    data.snapshot.id = data.digest()
    metadata = data.model_copy(update={'events': []})
    body = {'type': 'MatchEvent', 'version': 1,
            'snapshot': metadata.model_dump(mode='json'),
            'event': data.events[-1].model_dump(mode='json')}
    publisher = Publisher(service)
    return service, publisher, body


def delivery(body):
    return SimpleNamespace(body_as_str=lambda: json.dumps(body))


def test_ready_notification_follows_both_stores_and_precedes_checkpoint(setup):
    service, publisher, body = setup
    partition = Partition()
    handler = MatchEventHandler(service, publisher, retry_seconds=0)
    message = delivery(body)
    asyncio.run(handler.on_event(partition, message))
    assert partition.checkpoints == [message]
    assert publisher.messages[0].events == []
    assert service.payload(body['snapshot']['snapshot']['id']).events


def test_retry_after_notification_failure_preserves_idempotent_stores(setup):
    service, publisher, body = setup
    publisher.fail_once = True
    partition = Partition()
    handler = MatchEventHandler(service, publisher, retry_seconds=0)
    asyncio.run(handler.on_event(partition, delivery(body)))
    assert publisher.calls == 2
    assert len(service.history.rows) == len(service.stats.rows) == 1
    assert len(partition.checkpoints) == 1


def test_retry_incomplete_store_before_notification(setup):
    service, publisher, body = setup
    save = service.stats.save
    attempts = []

    def save_after_failure(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError('Temporary database outage')
        save(*args)

    service.stats.save = save_after_failure
    asyncio.run(MatchEventHandler(service, publisher, 0).on_event(Partition(), delivery(body)))
    assert len(attempts) == 2
    assert publisher.calls == 1


@pytest.mark.parametrize('change', ['event', 'cursor', 'hash', 'events', 'version'])
def test_invalid_message_is_rejected_without_notification_or_storage(setup, change):
    service, publisher, body = setup
    if change == 'event': body['event']['event_type'] = 'goal'
    elif change == 'cursor': body['snapshot']['snapshot']['cursor'] = 99
    elif change == 'hash': body['snapshot']['snapshot']['recording_hash'] = 'foreign'
    elif change == 'events': body['snapshot']['events'] = [body['event']]
    else: body['version'] = 2
    partition = Partition()
    asyncio.run(MatchEventHandler(service, publisher).on_event(partition, delivery(body)))
    assert len(partition.checkpoints) == 1
    assert not service.history.rows
    assert publisher.calls == 0


def test_initial_recovery_metadata_can_omit_last_event(setup):
    service, publisher, body = setup
    body['event'] = None
    asyncio.run(MatchEventHandler(service, publisher).on_event(Partition(), delivery(body)))
    assert publisher.calls == 1


@pytest.mark.parametrize('body', [{'type': 'IntegrationProbe'}, {'type': 'FutureMessage'}, []])
def test_probe_unknown_or_poison_is_skipped(setup, body):
    service, publisher, _ = setup
    partition = Partition()
    asyncio.run(MatchEventHandler(service, publisher).on_event(partition, delivery(body)))
    assert len(partition.checkpoints) == 1
    assert publisher.calls == 0


def test_cancellation_does_not_ack_inflight_failure(setup):
    service, publisher, body = setup
    service.stats.fail = True
    partition = Partition()

    async def run():
        task = asyncio.create_task(MatchEventHandler(service, publisher).on_event(partition, delivery(body)))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert not partition.checkpoints
    assert publisher.calls == 0


def test_lifespan_owns_brokers_and_http_publication_is_disabled(setup):
    service, _, body = setup

    class Brokers:
        started = False
        closed = False
        async def start(self): self.started = True
        async def close(self): self.closed = True
        def status(self): return {'transport': 'event-hubs/service-bus'}

    brokers = Brokers()
    with TestClient(create_app(service, brokers=brokers)) as client:
        assert brokers.started
        assert client.get('/health').json()['transport'] == 'event-hubs/service-bus'
        assert client.get('/demo/recording').status_code == 200
        for route in ('/demo/snapshots', '/demo/viewer-snapshots', '/demo/question-snapshots',
                      '/dev/viewer-snapshots', '/dev/question-snapshots'):
            assert client.post(route, json=body['snapshot']).status_code == 409
    assert brokers.closed


def test_runtime_shutdown_cancels_receiver_and_closes_clients():
    class Client:
        closed = False
        async def close(self): self.closed = True

    async def run():
        runtime = BrokerRuntime.__new__(BrokerRuntime)
        runtime.consumer = Client()
        runtime.publisher = Client()
        runtime.task = asyncio.create_task(asyncio.sleep(100))
        await runtime.close()
        assert runtime.task.cancelled()
        assert runtime.consumer.closed and runtime.publisher.closed
    asyncio.run(run())
