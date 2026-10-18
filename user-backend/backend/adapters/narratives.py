"""Neutral narrative transport boundary. Broker payload is a versioned JSON document."""
import asyncio
import json
import logging

import httpx
from pydantic import ValidationError

from ..domain import RuleError
from ..models.narratives import NeutralNarrative

logger = logging.getLogger(__name__)


class NarrativeHistory:
    def __init__(self, url):
        self.url = url

    async def replay(self, service, *, max_pages=100):
        cursor, seen, processed = None, set(), 0
        async with httpx.AsyncClient(timeout=15) as client:
            for _ in range(max_pages):
                response = await client.post(self.url, json={
                    'query': 'query($id:ID!,$after:String){neutralNarratives(matchId:$id,after:$after)}',
                    'variables': {'id': service.match_id, 'after': cursor}})
                response.raise_for_status()
                body = response.json()
                if body.get('errors'):
                    raise RuleError('history_unavailable', 'Neutral narrative history query failed', 503)
                page = body['data']['neutralNarratives']
                for document in page['items']:
                    await service.receive(NeutralNarrative.model_validate(document))
                    processed += 1
                cursor = page['next_cursor']
                if cursor is None:
                    return processed
                if cursor in seen:
                    raise RuleError('history_cursor', 'Narrative history returned a repeated cursor', 503)
                seen.add(cursor)
        raise RuleError('history_limit', 'Narrative history exceeded the page limit', 503)


async def settle_narrative(receiver, message, service, notify):
    """Settle only after durable variants and notification; redelivery reuses stored work."""
    try:
        document = NeutralNarrative.model_validate(json.loads(str(message)))
        await service.receive(document)
        await notify('neutral_narrative_received')
    except (ValidationError, json.JSONDecodeError):
        await receiver.dead_letter_message(message, reason='invalid_neutral_narrative')
    except RuleError as exc:
        if exc.status < 500:
            await receiver.dead_letter_message(message, reason=exc.code)
        else:
            await receiver.abandon_message(message)
            await asyncio.sleep(1)
    else:
        await receiver.complete_message(message)


class NarrativeBusConsumer:
    def __init__(self, connection_string, service, notify, *, topic='narratives', subscription='user-backend'):
        self.connection_string, self.service, self.notify = connection_string, service, notify
        self.topic, self.subscription, self.connected = topic, subscription, False

    async def run(self):
        from azure.servicebus.aio import ServiceBusClient, AutoLockRenewer
        while True:
            try:
                async with ServiceBusClient.from_connection_string(self.connection_string) as client:
                    async with AutoLockRenewer(max_lock_renewal_duration=
                        self.service.timeout * max(1, self.service.max_variants) + 60) as renewer:
                        async with client.get_subscription_receiver(
                            self.topic, self.subscription, prefetch_count=0, auto_lock_renewer=renewer
                        ) as receiver:
                            self.connected = True
                            async for message in receiver:
                                await settle_narrative(receiver, message, self.service, self.notify)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never log broker credentials or provider exception bodies.
                logger.warning('Narrative subscription disconnected; retrying')
                self.connected = False
                await asyncio.sleep(2)
            finally:
                self.connected = False
