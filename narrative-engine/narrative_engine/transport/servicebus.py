"""Service Bus: receive ETL notifications and presence, publish narratives.

A message is completed once its handler returns: the handler only records it in the match's
Cosmos checkpoint, and the model work runs later in that match's worker. It is abandoned on
failure so Service Bus redelivers it (dead-lettering after the subscription's max delivery
count), and dead-lettered at once if it is not JSON. Locks are still auto-renewed as a safety
net for slow handlers.
"""
import asyncio
import json
import logging

from azure.servicebus import ServiceBusMessage
from azure.servicebus.exceptions import ServiceBusError
from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient

from narrative_engine.transport.files import narrative_doc

log = logging.getLogger(__name__)


def message_type(message):
    """The ETL's `notificationType` application property, if any (keys arrive as bytes)."""
    props = message.application_properties or {}
    value = props.get(b"notificationType", props.get("notificationType"))
    return value.decode() if isinstance(value, bytes) else value


class ServiceBusPublisher:
    def __init__(self, connection_string, topic="narratives"):
        self.client = ServiceBusClient.from_connection_string(connection_string)
        self.sender = self.client.get_topic_sender(topic)
        self.opened, self.open_lock = False, asyncio.Lock()

    async def publish(self, narrative):
        # Open the link once before concurrent sends: concurrent first sends on an unopened sender
        # race inside the SDK ("'NoneType' object has no attribute 'create_sender_link'").
        if not self.opened:
            async with self.open_lock:
                if not self.opened:
                    await self.sender.__aenter__()
                    self.opened = True
        await self.sender.send_messages(ServiceBusMessage(
            json.dumps(narrative_doc(narrative)), message_id=narrative.id, content_type="application/json",
            subject="Narrative", application_properties={"userType": narrative.userType, "matchId": narrative.matchId}))

    async def aclose(self):
        await self.sender.close()
        await self.client.close()


async def settle(receiver, message, handle, fixed_type=None):
    """Run `handle(body, messageType)` for one message, then complete, abandon or dead-letter it."""
    try:
        body = json.loads(b"".join(message.body))
    except (ValueError, TypeError) as error:
        log.error("dead-lettering unreadable message %s: %s", message.message_id, error)
        await receiver.dead_letter_message(message, reason="unreadable", error_description=str(error)[:200])
        return
    try:
        await handle(body, fixed_type or message_type(message))
    except Exception:
        log.exception("abandoning message %s (delivery %s)", message.message_id, message.delivery_count)
        settlement = receiver.abandon_message
    else:
        settlement = receiver.complete_message
    try:
        await settlement(message)
    except ServiceBusError as error:  # e.g. lock lost: Service Bus redelivers, and handlers are idempotent
        log.warning("could not settle message %s: %s", message.message_id, error)


class SubscriptionListener:
    """Receives one topic subscription and settles each message after `handle`; up to
    `concurrency` messages are in flight at once."""

    def __init__(self, connection_string, topic, subscription, handle, fixed_type=None, concurrency=8,
                 max_lock_renewal=1800):
        self.connection_string, self.topic, self.subscription = connection_string, topic, subscription
        self.handle, self.fixed_type = handle, fixed_type
        self.concurrency, self.max_lock_renewal = concurrency, max_lock_renewal

    async def run(self):
        slots = asyncio.Semaphore(self.concurrency)
        tasks = set()

        async def one(receiver, message):
            try:
                await settle(receiver, message, self.handle, self.fixed_type)
            finally:
                slots.release()

        async with ServiceBusClient.from_connection_string(self.connection_string) as client, \
                AutoLockRenewer(max_lock_renewal_duration=self.max_lock_renewal) as renewer:
            receiver = client.get_subscription_receiver(self.topic, self.subscription)
            async with receiver:
                log.info("listening on %s/%s", self.topic, self.subscription)
                while True:
                    await slots.acquire()
                    slots.release()
                    for message in await receiver.receive_messages(max_message_count=self.concurrency,
                                                                   max_wait_time=5):
                        renewer.register(receiver, message)
                        await slots.acquire()
                        task = asyncio.create_task(one(receiver, message))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
