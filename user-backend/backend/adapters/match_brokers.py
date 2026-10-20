"""Azure SDK transports. Callbacks return only after application persistence."""
import asyncio
import json
import logging
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pydantic import ValidationError
from backend.models.broker import MatchDelivery, BucketDelivery

log = logging.getLogger(__name__)


class MatchBrokers:
    def __init__(self, event_connection, narrative_connection, *, hub='match-events',
                 group='user-backend', topic='narratives', subscription='user-backend'):
        self.event_connection, self.narrative_connection = event_connection, narrative_connection
        self.hub, self.group, self.topic, self.subscription = hub, group, topic, subscription
        self._stack = AsyncExitStack()

    async def open(self):
        from azure.eventhub.aio import EventHubProducerClient
        self.producer = await self._stack.enter_async_context(EventHubProducerClient.from_connection_string(
            self.event_connection, eventhub_name=self.hub, retry_total=3))

    async def close(self):
        await self._stack.aclose()

    async def publish(self, payload, event=None):
        from azure.eventhub import EventData
        body = payload.model_dump(mode='json', exclude={'events'}) | {'events': []}
        batch = await self.producer.create_batch(partition_key=payload.snapshot.match_id)
        batch.add(EventData(json.dumps({'type': 'MatchEvent', 'version': 1,
            'snapshot': body, 'event': event.model_dump(mode='json') if event else None})))
        await self.producer.send_batch(batch)

    async def events(self, accept):
        from azure.eventhub.aio import EventHubConsumerClient

        async def receive(partition, event):
            if event is None:
                return
            try:
                body = json.loads(event.body_as_str())
                if not isinstance(body, dict) or body.get('type') != 'MatchEvent':
                    await partition.update_checkpoint(event)
                    return
                delivery = MatchDelivery.model_validate(body)
            except (ValueError, ValidationError):
                log.warning('Rejected invalid match envelope')
                await partition.update_checkpoint(event)
                return
            while True:
                try:
                    await accept(delivery)
                    await partition.update_checkpoint(event)
                    return
                except ValueError:
                    log.warning('Rejected inconsistent match delivery')
                    await partition.update_checkpoint(event)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.warning('Match event commit delayed; retrying')
                    await asyncio.sleep(1)

        while True:
            try:
                async with EventHubConsumerClient.from_connection_string(self.event_connection,
                        consumer_group=self.group, eventhub_name=self.hub) as client:
                    await client.receive(on_event=receive, starting_position='-1')
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('Match event connection interrupted; retrying')
                await asyncio.sleep(2)

    async def narratives(self, accept):
        from azure.servicebus.aio import ServiceBusClient, AutoLockRenewer
        while True:
            try:
                async with ServiceBusClient.from_connection_string(self.narrative_connection) as client:
                    async with AutoLockRenewer(max_lock_renewal_duration=300) as renewer:
                        async with client.get_subscription_receiver(self.topic, self.subscription,
                                prefetch_count=0, auto_lock_renewer=renewer) as receiver:
                            async for message in receiver:
                                await settle_bucket_message(receiver, message, accept)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('Bucket narrative connection interrupted; retrying')
                await asyncio.sleep(2)


async def settle_bucket_message(receiver, message, accept):
    try:
        body = json.loads(str(message))
        if isinstance(body, dict) and body.get('type') == 'IntegrationProbe':
            await receiver.complete_message(message)
            return
        delivery = BucketDelivery.model_validate(body)
    except (ValueError, ValidationError):
        await receiver.dead_letter_message(message, reason='invalid_bucket_delivery')
        return
    retry_delay = 1
    while True:
        try:
            await accept(delivery)
        except ValueError:
            await receiver.dead_letter_message(message, reason='inconsistent_bucket_delivery')
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Retry under the renewable lock rather than rapidly exhausting the
            # subscription's delivery count during a short database outage.
            locked_until = getattr(message, 'locked_until_utc', None)
            if getattr(message, 'auto_renew_error', None) is not None or (
                    locked_until is not None and locked_until <= datetime.now(timezone.utc)):
                raise RuntimeError('Narrative lock expired during persistence retry') from exc
            log.warning('Narrative persistence delayed; retrying current delivery')
            await asyncio.sleep(retry_delay)
            retry_delay = min(15, retry_delay * 2)
        else:
            await receiver.complete_message(message)
            return
