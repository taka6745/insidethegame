"""Event Hubs ingress and Service Bus readiness publication for demo ETL."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from demo_etl.models.broker import MatchEventMessage

log = logging.getLogger(__name__)
STARTUP_WINDOW = timedelta(minutes=2)


class SnapshotPublisher:
    def __init__(self, connection_string, topic):
        from azure.servicebus.aio import ServiceBusClient
        self.client = ServiceBusClient.from_connection_string(connection_string)
        self.sender = self.client.get_topic_sender(topic_name=topic)

    async def publish(self, snapshot):
        await self.publish_many([snapshot])

    async def publish_many(self, snapshots):
        """Every committed snapshot is announced, in order, in as few size-bounded sends as fit."""
        from azure.servicebus import ServiceBusMessage
        batch = await self.sender.create_message_batch()
        for snapshot in snapshots:
            message = ServiceBusMessage(
                json.dumps({'type': 'MatchSnapshotReady', 'version': 1, 'snapshot': snapshot.model_dump(mode='json')}),
                content_type='application/json', message_id=snapshot.snapshot.id, subject='MatchSnapshotReady')
            try:
                batch.add_message(message)
            except ValueError:  # MessageSizeExceededError: send what fits, start a new batch.
                await self.sender.send_messages(batch)
                batch = await self.sender.create_message_batch()
                batch.add_message(message)
        if len(batch):
            await self.sender.send_messages(batch)

    async def close(self):
        await self.sender.close()
        await self.client.close()


class MatchEventHandler:
    """Commit both stores, publish readiness, then checkpoint the delivery."""
    def __init__(self, service, publisher, retry_seconds=1):
        self.service = service
        self.publisher = publisher
        self.retry_seconds = retry_seconds

    def parse(self, body):
        message = self.envelope(body)
        return message and self.verify(message)

    def envelope(self, body):
        """Cheap shape check; verify() does the O(history) recording comparison."""
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError('Expected an object')
        if data.get('type') != 'MatchEvent':
            return None
        return MatchEventMessage.model_validate(data)

    def verify(self, message):
        recording = self.service.recording
        if recording is None:
            raise ValueError('Recording is not configured')
        # Materialisation is a replaceable stub recovery mechanism, not live ETL.
        materialised = recording.materialise(message.snapshot)
        materialised.validate_identity()
        if message.event is not None:
            # Fields the producer states must match; omitted v3 fields come from the ETL-owned recording.
            stated = message.event.model_dump(exclude_unset=True)
            if not materialised.events or any(
                    getattr(materialised.events[-1], key) != value for key, value in stated.items()):
                raise ValueError('Event does not match its recording cursor')
        return message

    async def on_event(self, partition, event):
        await self.on_event_batch(partition, [event])

    async def on_event_batch(self, partition, events):
        """Commit and announce only the newest snapshot of each run in a delivery batch, then
        checkpoint once. Its history includes every earlier event, and readers pin to announced
        snapshots, so a backlog costs one O(history) commit instead of one per delivery."""
        if not events:
            return
        newest = {}
        for event in events:
            try:
                message = self.envelope(event.body_as_str())
            except (ValueError, KeyError, TypeError):
                log.warning('Rejected invalid match broker message')
                continue
            if message is not None:
                newest.pop(message.snapshot.snapshot.run_id, None)
                newest[message.snapshot.snapshot.run_id] = message
        committed = []
        for message in newest.values():
            try:
                self.verify(message)
            except (ValueError, KeyError, TypeError):
                log.warning('Rejected invalid match broker message')
                continue
            if await self._commit(message):
                committed.append(message.snapshot)
        while committed:
            try:
                await self.publisher.publish_many(committed)
                break
            except Exception as exc:
                log.warning('Match broker delivery will retry (%s)', type(exc).__name__)
                await asyncio.sleep(self.retry_seconds)
        while True:
            try:
                await partition.update_checkpoint(events[-1])
                return
            except Exception as exc:
                log.warning('Match broker checkpoint will retry (%s)', type(exc).__name__)
                await asyncio.sleep(self.retry_seconds)

    async def _commit(self, message):
        while True:
            try:
                await asyncio.to_thread(self.service.publish, message.snapshot, owned=True)
                return True
            except ValueError:
                # Conflicting immutable state is poison, not an outage.
                log.warning('Rejected conflicting match broker message')
                return False
            except Exception as exc:
                log.warning('Match broker delivery will retry (%s)', type(exc).__name__)
                await asyncio.sleep(self.retry_seconds)


class BrokerRuntime:
    def __init__(self, service, eventhub_connection, eventhub_name,
                 servicebus_connection, servicebus_topic):
        from azure.eventhub.aio import EventHubConsumerClient
        self.publisher = SnapshotPublisher(servicebus_connection, servicebus_topic)
        self.consumer = EventHubConsumerClient.from_connection_string(
            eventhub_connection, consumer_group='etl', eventhub_name=eventhub_name)
        self.handler = MatchEventHandler(service, self.publisher)
        self.task = None

    async def start(self):
        self.task = asyncio.create_task(self.run(), name='etl-event-hubs')

    async def run(self):
        # No durable checkpoint store locally. Start shortly before now, so a watermark the backend
        # published while ETL was starting is still committed, without replaying every earlier run in
        # retention; ETL rebuilds each snapshot's prefix from its own recording. Reconnects resume
        # each partition after its last handled delivery.
        start, resume = datetime.now(timezone.utc) - STARTUP_WINDOW, {}

        async def handle(partition, events):
            await self.handler.on_event_batch(partition, events)
            if events:
                resume[partition.partition_id] = events[-1].enqueued_time

        while True:
            try:
                partitions = await self.consumer.get_partition_ids()
                await self.consumer.receive_batch(on_event_batch=handle, max_batch_size=100,
                                                  starting_position={p: resume.get(p, start) for p in partitions})
            except Exception as exc:
                log.warning('Event Hubs receiver will reconnect (%s)', type(exc).__name__)
            await asyncio.sleep(1)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        try:
            await self.consumer.close()
        finally:
            await self.publisher.close()

    def status(self):
        return {'transport': 'event-hubs/service-bus',
                'consumer_running': self.task is not None and not self.task.done()}
