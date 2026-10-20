"""Service Bus ingress for already-bucketed narratives; never calls a model."""
import asyncio
import json
import logging

from pydantic import ValidationError

from ..domain import Narrative, RuleError

logger = logging.getLogger(__name__)


async def settle_narrative(receiver, message, deliver):
    try:
        narrative = Narrative.model_validate(json.loads(str(message)))
        await deliver(narrative)
    except (ValidationError, json.JSONDecodeError):
        await receiver.dead_letter_message(message, reason='invalid_bucket_narrative')
    except RuleError as exc:
        if exc.status < 500:
            await receiver.dead_letter_message(message, reason=exc.code)
        else:
            await receiver.abandon_message(message)
            await asyncio.sleep(1)
    else:
        await receiver.complete_message(message)


class NarrativeBusConsumer:
    def __init__(self, connection_string, deliver, *, topic='narratives', subscription='user-backend'):
        self.connection_string, self.deliver = connection_string, deliver
        self.topic, self.subscription = topic, subscription

    async def run(self):
        from azure.servicebus.aio import ServiceBusClient, AutoLockRenewer
        while True:
            try:
                async with ServiceBusClient.from_connection_string(self.connection_string) as client:
                    async with AutoLockRenewer(max_lock_renewal_duration=120) as renewer:
                        async with client.get_subscription_receiver(
                            self.topic, self.subscription, prefetch_count=0, auto_lock_renewer=renewer
                        ) as receiver:
                            async for message in receiver:
                                await settle_narrative(receiver, message, self.deliver)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Exception bodies can contain credentials or provider payloads.
                logger.warning('Narrative subscription disconnected; retrying')
                await asyncio.sleep(2)
