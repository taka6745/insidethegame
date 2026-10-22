"""Event Hubs consumer against a fake client: a hub reset while connected is detected at runtime."""
import asyncio
import json
import logging
from datetime import datetime

from backend.adapters.match_stream import MatchStream


class Repository:
    def __init__(self, stored):
        self.stored, self.reset = dict(stored), []

    def checkpoints(self):
        return dict(self.stored)

    def checkpoint(self, partition, seq):
        self.stored[partition] = max(self.stored.get(partition, -1), seq)

    def reset_checkpoint(self, partition):
        self.reset.append(partition)
        self.stored.pop(partition, None)


class Registry:
    def __init__(self, repository):
        self.repository = repository

    def gaps(self):
        return []

    async def checkpoint(self, checkpoint):
        self.repository.checkpoint(*checkpoint)

    async def accept_info(self, info):
        return True

    async def accept_events(self, envelopes):
        return len(envelopes)


class Event:
    def __init__(self, seq):
        self.sequence_number = seq

    def body_as_str(self):
        return json.dumps({'feed': 'MA3'})  # Ignored by the backend; only the position matters.


class Hub:
    """One partition. Each connection records its starting positions and delivers `deliver`."""

    def __init__(self, last, deliver=()):
        self.last, self.deliver, self.connections = last, list(deliver), []

    def client(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_partition_ids(self):
        return ['0']

    async def get_partition_properties(self, partition):
        return {'last_enqueued_sequence_number': self.last}

    async def receive_batch(self, on_event_batch, starting_position, **options):
        self.connections.append(dict(starting_position))
        if self.deliver:
            await on_event_batch(type('Partition', (), {'partition_id': '0'})(), [Event(s) for s in self.deliver])
            self.deliver = []
        await asyncio.Event().wait()  # Like the SDK: waits on its offsets, never errors.


def test_a_hub_reset_while_connected_is_detected_and_resumes_from_latest(caplog):
    async def scenario():
        repository = Repository({'0': 40})
        hub = Hub(last=50, deliver=[41, 42])
        stream = MatchStream('unused')
        stream.client = hub.client
        task = asyncio.create_task(stream.run(Registry(repository), check_seconds=0.01))
        while not hub.connections:
            await asyncio.sleep(0.01)
        assert hub.connections[0] == {'0': 40}
        await asyncio.sleep(0.05)
        assert repository.stored == {'0': 42} and len(hub.connections) == 1  # Healthy: no reconnect.
        hub.last = 3  # The emulator restarted: sequence numbers begin again at 0.
        while len(hub.connections) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        return repository, hub

    with caplog.at_level(logging.WARNING):
        repository, hub = asyncio.run(scenario())
    assert repository.reset == ['0'] and '0' not in repository.stored
    assert isinstance(hub.connections[1]['0'], datetime)  # Latest, not the stale sequence number.
    assert 'the hub was reset' in caplog.text


def test_a_stored_position_past_the_end_at_connect_starts_from_latest(caplog):
    async def scenario():
        repository, hub = Repository({'0': 900}), Hub(last=10)
        stream = MatchStream('unused')
        stream.client = hub.client
        task = asyncio.create_task(stream.run(Registry(repository), check_seconds=60))
        while not hub.connections:
            await asyncio.sleep(0.01)
        task.cancel()
        return repository, hub

    with caplog.at_level(logging.WARNING):
        repository, hub = asyncio.run(scenario())
    assert isinstance(hub.connections[0]['0'], datetime) and repository.reset == ['0']
    assert 'the hub was reset' in caplog.text
