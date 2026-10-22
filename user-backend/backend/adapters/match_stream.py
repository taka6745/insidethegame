"""Azure SDK consumers: Event Hubs `match-events` (MA1, MatchEvent v2) and the Service Bus
`narratives` topic (narrative engine). Callbacks return only after the application commits.

Event Hubs positions are stored in Postgres beside the events they follow, so a restart
resumes where the last committed event left off."""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from pydantic import ValidationError

from backend.models.engine_narratives import EngineFollowClip, EngineMomentClip, EngineNarrative
from backend.models.match_stream import MatchEventV2, MatchInfo

log = logging.getLogger(__name__)


def parse_match_message(text):
    """('info', MatchInfo) | ('event', MatchEventV2) | None for messages this service does not use."""
    body = json.loads(text)
    if not isinstance(body, dict):
        raise ValueError('Not a JSON object')
    if body.get('type') == 'MatchEvent':
        return ('event', MatchEventV2.model_validate(body)) if body.get('version') == 2 else None
    if body.get('feed') == 'MA1':
        return 'info', MatchInfo.model_validate(body)
    return None  # MA3 and POS belong to ETL.


async def handle_match_messages(texts, registry, checkpoint=None):
    """Validate and commit a partition's batch: each match's MatchEvents in one transaction,
    MA1s in order before them. The position is stored only after everything committed and while
    no match is missing a seq, so a restart replays events held behind a gap. Invalid messages are
    logged and skipped (their seq becomes a gap)."""
    pending = {}

    async def flush():
        for envelopes in pending.values():
            await registry.accept_events(envelopes)
        pending.clear()

    for text in texts:
        try:
            parsed = parse_match_message(text)
        except (ValueError, ValidationError):
            log.warning('Rejected an invalid match message')
            continue
        if parsed is None:
            continue
        kind, message = parsed
        if kind == 'info':
            await flush()
            await registry.accept_info(message)
        else:
            pending.setdefault(message.matchId, []).append(message)
    await flush()
    if checkpoint and not registry.gaps():
        await registry.checkpoint(checkpoint)


async def handle_match_message(text, checkpoint, registry):
    await handle_match_messages([text], registry, checkpoint)


class MatchStream:
    def __init__(self, event_connection, *, hub='match-events', group='user-backend', start='latest', batch=300):
        if start not in ('latest', 'earliest'):
            raise ValueError('MATCH_EVENTHUB_START must be latest or earliest')
        self.event_connection, self.hub, self.group, self.start = event_connection, hub, group, start
        self.batch = batch

    @classmethod
    def from_env(cls):
        return cls(os.environ['MATCH_EVENTHUB_CONNECTION_STRING'], hub=os.getenv('MATCH_EVENTHUB_NAME', 'match-events'),
                   group=os.getenv('MATCH_EVENTHUB_CONSUMER_GROUP', 'user-backend'),
                   start=os.getenv('MATCH_EVENTHUB_START', 'latest'))

    def client(self):
        from azure.eventhub.aio import EventHubConsumerClient
        return EventHubConsumerClient.from_connection_string(
            self.event_connection, consumer_group=self.group, eventhub_name=self.hub)

    async def run(self, registry, *, check_seconds=5.0):
        # Partitions without a stored position start now (or at the retention start when
        # configured); tombstones and the purge cut-off keep cleared matches out either way.
        first = datetime.now(timezone.utc) if self.start == 'latest' else '-1'
        resume, restart = {}, {}  # restart: where a reset partition starts instead of `first`.

        async def reset(client, positions):
            """A position past the partition's last sequence number: the hub was recreated (the
            emulator restarts at 0). Forget it and start from now ("latest") or the retention
            start. True if any was."""
            found = False
            for p, position in list(positions.items()):
                last = (await client.get_partition_properties(p))['last_enqueued_sequence_number']
                if isinstance(position, int) and position > last:
                    log.warning('Event Hubs partition %s ends at %s, before position %s: the hub was reset; '
                                'resuming from %s', p, last, position, self.start)
                    await asyncio.to_thread(registry.repository.reset_checkpoint, p)
                    resume.pop(p, None)
                    positions[p] = restart[p] = datetime.now(timezone.utc) if self.start == 'latest' else '-1'
                    found = True
            return found

        async def watch(client, positions):
            # While connected the SDK keeps waiting on old offsets after a reset, without an error.
            while True:
                await asyncio.sleep(check_seconds)
                if await reset(client, {p: resume.get(p, positions[p]) for p in positions}):
                    return

        async def receive(partition, events):
            if not events:
                return
            checkpoint = (partition.partition_id, events[-1].sequence_number)
            while True:
                try:
                    await handle_match_messages([e.body_as_str() for e in events], registry, checkpoint)
                    resume[partition.partition_id] = events[-1].sequence_number
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.warning('Match message commit delayed; retrying', exc_info=True)
                    await asyncio.sleep(1)

        while True:
            try:
                stored = await asyncio.to_thread(registry.repository.checkpoints)
                async with self.client() as client:
                    partitions = await client.get_partition_ids()
                    positions = {p: resume.get(p, stored.get(p, restart.get(p, first))) for p in partitions}
                    await reset(client, positions)
                    # Batches: one transaction per match per batch, not one per event.
                    receiving = asyncio.create_task(client.receive_batch(
                        on_event_batch=receive, max_batch_size=self.batch, max_wait_time=0.2,
                        starting_position=positions,
                        starting_position_inclusive={p: False for p in partitions if isinstance(positions[p], int)}))
                    watching = asyncio.create_task(watch(client, positions))
                    try:
                        await asyncio.wait({receiving, watching}, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in (receiving, watching):
                            task.cancel()
                        await asyncio.gather(receiving, watching, return_exceptions=True)
                    if receiving.done() and not receiving.cancelled() and receiving.exception():
                        raise receiving.exception()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('Match event connection interrupted; retrying')
                await asyncio.sleep(2)


class NarrativeStream:
    def __init__(self, connection, *, topic='narratives', subscription='user-backend'):
        self.connection, self.topic, self.subscription = connection, topic, subscription

    @classmethod
    def from_env(cls):
        return cls(os.environ['NARRATIVE_SERVICEBUS_CONNECTION_STRING'],
                   topic=os.getenv('NARRATIVE_SERVICEBUS_TOPIC', 'narratives'),
                   subscription=os.getenv('NARRATIVE_SERVICEBUS_SUBSCRIPTION', 'user-backend'))

    async def run(self, accept):
        from azure.servicebus.aio import AutoLockRenewer, ServiceBusClient
        while True:
            try:
                async with ServiceBusClient.from_connection_string(self.connection) as client:
                    async with AutoLockRenewer(max_lock_renewal_duration=300) as renewer:
                        async with client.get_subscription_receiver(self.topic, self.subscription,
                                prefetch_count=0, auto_lock_renewer=renewer) as receiver:
                            async for message in receiver:
                                await settle_narrative_message(receiver, message, accept)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('Narrative connection interrupted; retrying')
                await asyncio.sleep(2)


async def settle_narrative_message(receiver, message, accept):
    """One engine narrative (`userType`, no `type`), follow clip (`type: FollowClip`) or key-event clip (`type:
    MomentClip`). Probes complete; anything else dead-letters."""
    try:
        body = json.loads(str(message))
        if isinstance(body, dict) and body.get('type') == 'IntegrationProbe':
            await receiver.complete_message(message)
            return
        if isinstance(body, dict) and body.get('type') == 'FollowClip':
            narrative = EngineFollowClip.model_validate(body)
        elif isinstance(body, dict) and body.get('type') == 'MomentClip':
            narrative = EngineMomentClip.model_validate(body)
        elif not isinstance(body, dict) or 'type' in body or 'userType' not in body:
            raise ValueError('Not an engine narrative')
        else:
            narrative = EngineNarrative.model_validate(body)
    except (ValueError, ValidationError):
        await receiver.dead_letter_message(message, reason='invalid_narrative')
        return
    retry_delay = 1
    while True:
        try:
            await accept(narrative)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Retry under the renewable lock rather than exhausting the delivery count during a
            # short database outage.
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
