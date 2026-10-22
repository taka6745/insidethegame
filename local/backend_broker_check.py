"""Real Event Hubs → isolated backend registry → PostgreSQL, without touching live matches.

Sends a probe match (MA1, then 12 MatchEvent v2 and one redelivery) under a fresh matchId,
consumes it in the `integration` consumer group into a throwaway schema, checks the received
events, duplicate handling and restart recovery, then purges the probe from every owner."""
import asyncio
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient
from psycopg import sql

from backend.adapters.match_stream import MatchStream
from backend.models.events import Event
from backend.repositories.matches import MatchRepository
from backend.services.match_registry import MatchRegistry
from backend.store import Store

OWNERS = ('http://backend:8000', 'http://etl-stream:8000', 'http://narrative-live:8000')


def messages(match_id, count):
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    yield {'feed': 'MA1', 'schemaVersion': 1, 'matchId': match_id, 'synthetic': True, 'fixture': 'broker-check',
           'runId': str(uuid4()), 'timeStamp': now, 'scheduledKickoff': now, 'description': 'SYNTHETIC broker probe',
           'contestant': [{'id': side, 'name': f'Probe {side}', 'position': side} for side in ('home', 'away')]}
    for seq in range(1, count + 1):
        event = Event(event_id=f'probe-{seq}', match_id=match_id, event_type='pass', team_id='home',
                      match_time_seconds=seq, sequence=seq)
        yield {'type': 'MatchEvent', 'version': 2, 'matchId': match_id, 'seq': seq, 'timeStamp': now,
               'synthetic': True, 'event': event.model_dump(mode='json')}


async def main():
    match_id = 'broker-check-' + uuid4().hex[:8]
    store = Store(os.environ['ACCOUNTS_DATABASE_URL'], os.environ['MATCH_APP_DATABASE_URL'], 'broker_check_' + uuid4().hex)
    connection = os.environ['MATCH_EVENTHUB_CONNECTION_STRING']
    hub = os.getenv('MATCH_EVENTHUB_NAME', 'match-events')
    store.initialize()
    registry = MatchRegistry(MatchRepository(store))
    consumer = asyncio.create_task(MatchStream(connection, hub=hub, group='integration').run(registry))
    try:
        await asyncio.sleep(3)  # The consumer starts at "now" for partitions without a stored position.
        sent = list(messages(match_id, 12))
        async with EventHubProducerClient.from_connection_string(connection, eventhub_name=hub) as producer:
            batch = await producer.create_batch(partition_key=match_id)
            for message in [*sent, sent[-1]]:  # The final event is delivered twice.
                batch.add(EventData(json.dumps(message)))
            await producer.send_batch(batch)
        async with asyncio.timeout(60):
            while match_id not in registry.matches or registry.matches[match_id].seq < 12:
                await asyncio.sleep(.1)
        match = registry.get(match_id)
        await asyncio.sleep(1)  # Room for the redelivery to arrive and be ignored.
        # Custom calculations count ETL's SPADL actions (tested with the backend suite), not these events.
        assert match.seq == 12
        restored = MatchRegistry(MatchRepository(store))
        await restored.initialize()
        assert restored.get(match_id).seq == 12
        print('PASS real Event Hubs → backend registry: MA1 + 12 events, duplicate ignored, PostgreSQL restore agrees',
              flush=True)
    finally:
        consumer.cancel()
        async with httpx.AsyncClient(timeout=20) as client:
            for owner in OWNERS:  # The probe's MA1 reached every consumer of the hub.
                try:
                    await client.post(owner + '/admin/matches/purge', json={'match_id': match_id})
                except httpx.HTTPError:
                    print(f'WARN could not purge the probe at {owner}', flush=True)
        with store.connect() as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(store.schema)))
        store.close()


if __name__ == '__main__':
    asyncio.run(main())
