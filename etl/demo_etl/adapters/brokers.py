"""Event Hubs ingress and Service Bus readiness publication for demo ETL."""
import asyncio
import json
import logging

from demo_etl.models.broker import MatchEventMessage

log = logging.getLogger(__name__)


class SnapshotPublisher:
    def __init__(self, connection_string, topic):
        from azure.servicebus.aio import ServiceBusClient
        self.client = ServiceBusClient.from_connection_string(connection_string)
        self.sender = self.client.get_topic_sender(topic_name=topic)

    async def publish(self, snapshot):
        from azure.servicebus import ServiceBusMessage
        body = {'type': 'MatchSnapshotReady', 'version': 1,
                'snapshot': snapshot.model_dump(mode='json')}
        await self.sender.send_messages(ServiceBusMessage(
            json.dumps(body), content_type='application/json',
            message_id=snapshot.snapshot.id, subject='MatchSnapshotReady'))

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
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError('Expected an object')
        if data.get('type') != 'MatchEvent':
            return None
        message = MatchEventMessage.model_validate(data)
        recording = self.service.recording
        if recording is None:
            raise ValueError('Recording is not configured')
        # Materialisation is a replaceable stub recovery mechanism, not live ETL.
        materialised = recording.materialise(message.snapshot)
        materialised.validate_identity()
        if message.event is not None:
            if not materialised.events or message.event != materialised.events[-1]:
                raise ValueError('Event does not match its recording cursor')
        return message

    async def on_event(self, partition, event):
        try:
            message = self.parse(event.body_as_str())
        except (ValueError, KeyError, TypeError):
            log.warning('Rejected invalid match broker message')
            await partition.update_checkpoint(event)
            return
        if message is None:
            await partition.update_checkpoint(event)
            return
        while True:
            try:
                try:
                    await asyncio.to_thread(self.service.publish, message.snapshot, owned=True)
                except ValueError:
                    # Conflicting immutable state is poison, not an outage.
                    log.warning('Rejected conflicting match broker message')
                    await partition.update_checkpoint(event)
                    return
                await self.publisher.publish(message.snapshot)
                await partition.update_checkpoint(event)
                return
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
        while True:
            try:
                await self.consumer.receive(on_event=self.handler.on_event,
                                            starting_position='-1')
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
