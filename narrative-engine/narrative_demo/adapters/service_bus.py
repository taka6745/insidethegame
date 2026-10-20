"""Service Bus settlement and reconnect policy for the authored demo."""
import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime, timezone

from pydantic import ValidationError

from ..models.brokers import SnapshotReady
from ..services.broker_delivery import NarrativeDelivery

logger = logging.getLogger(__name__)


class NarrativePublisher:
    def __init__(self, sender):
        self.sender = sender

    async def send(self, body, message_id):
        from azure.servicebus import ServiceBusMessage
        message = ServiceBusMessage(json.dumps(body, separators=(',', ':')),
                                    content_type='application/json', message_id=message_id)
        await self.sender.send_messages(message)


async def handle_message(receiver, message, delivery):
    await handle_messages(receiver, [message], delivery)


async def handle_messages(receiver, messages, delivery):
    """Narrate only the newest snapshot of a backlog; older ones are settled unread.
    Live delivery needs only the latest cursor, and questions capture the current one."""
    ready = []
    for message in messages:
        try:
            body = json.loads(str(message))
            if isinstance(body, dict) and body.get('type') == 'IntegrationProbe':
                await receiver.complete_message(message)
                continue
            ready.append((message, SnapshotReady.model_validate(body)))
        except (ValueError, TypeError, ValidationError):
            await receiver.dead_letter_message(message, reason='InvalidSnapshotNotification',
                                               error_description='Expected version 1 checkpoint metadata')
    if not ready:
        return
    message, notification = ready[-1]
    retry_delay = 1
    while True:
        try:
            await delivery.capture(notification.snapshot)
            break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Keep one delivery locked during upstream outages. Abandoning on
            # every attempt quickly exhausts the broker's delivery count when
            # a match is paused or finished and no later checkpoint can help.
            locked_until = getattr(message, 'locked_until_utc', None)
            if getattr(message, 'auto_renew_error', None) is not None or (
                    locked_until is not None and locked_until <= datetime.now(timezone.utc)):
                raise RuntimeError('Narrative message lock expired during retry') from exc
            logger.warning('Narrative delivery retry in %ss (%s)', retry_delay, type(exc).__name__)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 15)
    for message, _ in ready:
        await receiver.complete_message(message)


async def refresh_audiences(delivery, interval=2):
    while True:
        await asyncio.sleep(interval)
        try:
            await delivery.refresh()
        except Exception as exc:
            logger.warning('Narrative audience refresh will retry (%s)', type(exc).__name__)


class NarrativeBroker:
    def __init__(self, service, input_connection, output_connection, *,
                 input_topic='match-notifications', subscription='narrative-engine',
                 output_topic='narratives'):
        self.service = service
        self.input_connection, self.output_connection = input_connection, output_connection
        self.input_topic, self.subscription, self.output_topic = input_topic, subscription, output_topic

    async def run(self):
        from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient
        while True:
            try:
                async with ServiceBusClient.from_connection_string(self.input_connection) as source, \
                           ServiceBusClient.from_connection_string(self.output_connection) as destination, \
                           AutoLockRenewer(max_lock_renewal_duration=300) as renewer:
                    async with source.get_subscription_receiver(topic_name=self.input_topic,
                               subscription_name=self.subscription, prefetch_count=0,
                               auto_lock_renewer=renewer) as receiver, \
                               destination.get_topic_sender(topic_name=self.output_topic) as sender:
                        delivery = NarrativeDelivery(self.service, NarrativePublisher(sender))
                        refresh = asyncio.create_task(refresh_audiences(delivery))
                        try:
                            while True:
                                messages = await receiver.receive_messages(max_message_count=100, max_wait_time=2)
                                await handle_messages(receiver, messages, delivery)
                        finally:
                            refresh.cancel()
                            with suppress(asyncio.CancelledError):
                                await refresh
            except Exception as exc:
                logger.warning('Narrative broker reconnecting (%s)', type(exc).__name__)
                await asyncio.sleep(2)
