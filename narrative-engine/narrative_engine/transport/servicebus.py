"""Service Bus: receive ETL notifications, publish narratives.

A message is completed once its handler returns: the handler only records it in the match's
Cosmos checkpoint, and the model work runs later in that match's worker. It is abandoned on
failure so Service Bus redelivers it (dead-lettering after the subscription's max delivery
count), and dead-lettered at once if it is not JSON. Locks are still auto-renewed as a safety
net for slow handlers.
"""
import asyncio
import contextlib
import json
import logging

from azure.servicebus import ServiceBusMessage
from azure.servicebus.exceptions import (OperationTimeoutError, ServiceBusConnectionError, ServiceBusError,
                                         ServiceBusServerBusyError)
from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient

from narrative_engine.core.models import BrokerUnavailable
from narrative_engine.transport.files import narrative_doc

log = logging.getLogger(__name__)


def message_type(message):
    """The ETL's `notificationType` application property, if any (keys arrive as bytes)."""
    props = message.application_properties or {}
    value = props.get(b"notificationType", props.get("notificationType"))
    return value.decode() if isinstance(value, bytes) else value


class ServiceBusPublisher:
    """Sends are serialised: concurrent sends on one sender race inside the SDK ("'NoneType' object has
    no attribute 'create_sender_link'"), and once the handler shuts down it never recovers, so a failed
    send also replaces the sender (the step's retry then sends again)."""

    def __init__(self, connection_string, topic="narratives"):
        self.client = ServiceBusClient.from_connection_string(connection_string)
        self.topic, self.sender, self.lock = topic, None, asyncio.Lock()

    async def publish(self, narrative):
        await self._send(ServiceBusMessage(
            json.dumps(narrative_doc(narrative)), message_id=narrative.id, content_type="application/json",
            subject="Narrative", application_properties={"userType": narrative.userType, "matchId": narrative.matchId,
                                                         "kind": narrative.kind}))

    async def publish_clip(self, clip):
        """A moment clip (contracts Output 2: a follow's `FollowClip` or a key event's `MomentClip`), on the same
        topic."""
        await self._send(ServiceBusMessage(
            json.dumps(clip), message_id=clip["id"], content_type="application/json", subject=clip["type"],
            application_properties={"matchId": clip["matchId"], "kind": "clip"}))

    async def _send(self, message):
        async with self.lock:
            if self.sender is None:
                self.sender = self.client.get_topic_sender(self.topic)
            try:
                await self.sender.send_messages(message)
            except Exception as error:
                sender, self.sender = self.sender, None
                with contextlib.suppress(Exception):
                    await sender.close()
                if isinstance(error, (ServiceBusServerBusyError, ServiceBusConnectionError, OperationTimeoutError)):
                    raise BrokerUnavailable(f"narratives topic: {type(error).__name__}") from error
                raise

    async def aclose(self):
        if self.sender is not None:
            await self.sender.close()
        await self.client.close()


async def settle(receiver, message, handle):
    """Run `handle(body, messageType)` for one message, then complete, abandon or dead-letter it."""
    try:
        body = json.loads(b"".join(message.body))
    except (ValueError, TypeError) as error:
        log.error("dead-lettering unreadable message %s: %s", message.message_id, error)
        await receiver.dead_letter_message(message, reason="unreadable", error_description=str(error)[:200])
        return
    try:
        await handle(body, message_type(message))
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
    `concurrency` messages are in flight at once. A lost connection (broker restart, network)
    reconnects in-process with backoff, so the service keeps running; unsettled messages are
    redelivered after their locks expire."""

    def __init__(self, connection_string, topic, subscription, handle, concurrency=8,
                 max_lock_renewal=1800, retry_seconds=1.0, retry_max_seconds=30.0,
                 client_factory=ServiceBusClient.from_connection_string, lock_renewer=AutoLockRenewer):
        self.connection_string, self.topic, self.subscription = connection_string, topic, subscription
        self.handle = handle
        self.concurrency, self.max_lock_renewal = concurrency, max_lock_renewal
        self.retry_seconds, self.retry_max_seconds = retry_seconds, retry_max_seconds
        self.client_factory, self.lock_renewer = client_factory, lock_renewer
        self.connections, self.connected = 0, False

    async def run(self):
        delay = self.retry_seconds
        while True:
            try:
                await self._receive()
            except Exception as error:  # CancelledError is not an Exception: shutdown still stops it
                if self.connected:  # it had worked: start the backoff again
                    delay = self.retry_seconds
                log.warning("%s/%s receiver lost (%s); reconnecting in %.0fs", self.topic, self.subscription,
                            type(error).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.retry_max_seconds)

    async def _receive(self):
        slots = asyncio.Semaphore(self.concurrency)
        tasks = set()
        self.connected = False

        async def one(receiver, message):
            try:
                await settle(receiver, message, self.handle)
            finally:
                slots.release()

        self.connections += 1
        async with self.client_factory(self.connection_string) as client, \
                self.lock_renewer(max_lock_renewal_duration=self.max_lock_renewal) as renewer:
            receiver = client.get_subscription_receiver(self.topic, self.subscription)
            async with receiver:
                log.info("listening on %s/%s", self.topic, self.subscription)
                try:
                    while True:
                        await slots.acquire()
                        slots.release()
                        messages = await receiver.receive_messages(max_message_count=self.concurrency,
                                                                   max_wait_time=5)
                        self.connected = True
                        for message in messages:
                            renewer.register(receiver, message)
                            await slots.acquire()
                            task = asyncio.create_task(one(receiver, message))
                            tasks.add(task)
                            task.add_done_callback(tasks.discard)
                finally:  # let in-flight handlers settle on this receiver before it closes
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
