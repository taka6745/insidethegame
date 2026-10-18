"""Real broker → isolated backend index/inbox → durable DB, without moving the viewer."""
import asyncio
import os
from uuid import uuid4
import httpx
from psycopg import sql
from backend.adapters.match_brokers import MatchBrokers
from backend.adapters.replay_source import FixtureEventSource
from backend.models.rules import Rule
from backend.repositories.broker_inbox import NarrativeInbox
from backend.repositories.lab import PostgresLabRepository
from backend.services.broker_runtime import BrokerRuntime
from backend.services.lab import FilterLabService
from backend.services.question_snapshot import build_snapshot
from backend.store import Store


async def main():
    store = Store(os.environ['ACCOUNTS_DATABASE_URL'], os.environ['MATCH_APP_DATABASE_URL'],
                  'broker_check_' + uuid4().hex)
    store.initialize()
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(os.environ['DEMO_RECORDING_URL'])
        response.raise_for_status()
        source = FixtureEventSource(content=response.content)
        lab = FilterLabService(source, PostgresLabRepository(store), None)
        await lab.initialize()
        transport = MatchBrokers(os.environ['MATCH_EVENTHUB_CONNECTION_STRING'],
            os.environ['NARRATIVE_SERVICEBUS_CONNECTION_STRING'], group='integration', subscription='integration')
        inbox = NarrativeInbox(store)
        runtime = BrokerRuntime(lab, transport, inbox, timeout=60)
        duplicate_received = asyncio.Event()
        receipts = 0
        accept_event = runtime.accept_event
        async def observed_receipt(delivery):
            nonlocal receipts
            await accept_event(delivery)
            if delivery.snapshot.snapshot.run_id == str(lab.run_id) and delivery.snapshot.snapshot.cursor == 12 and delivery.event:
                receipts += 1
                if receipts >= 2:
                    duplicate_received.set()
        runtime.accept_event = observed_receipt
        await runtime.start()
        try:
            calculation = await lab.register(Rule(match_id=source.match_id), 'Captured actions')
            for _ in range(12):
                await lab.advance(finish=False)
            payload = build_snapshot(source, lab.run_id, lab.position)
            assert lab.engine.get(calculation['id']).value == 12
            # The same final event must not increment the index on redelivery.
            await transport.publish(payload, source.events[11])
            async with asyncio.timeout(60):
                await duplicate_received.wait()
                while not await asyncio.to_thread(inbox.read, payload.snapshot.id):
                    await asyncio.sleep(.1)
            assert lab.position == 12 and lab.engine.get(calculation['id']).value == 12
            restored = FilterLabService(source, PostgresLabRepository(store), None)
            await restored.initialize()
            assert restored.position == 12 and restored.engine.get(calculation['id']).value == 12
            print('PASS real Event Hubs → custom index: 12 events, duplicate ignored, PostgreSQL restore agrees', flush=True)
            print('PASS real Service Bus → durable backend narrative inbox', flush=True)
            metadata = payload.model_dump(mode='json', exclude={'events'}) | {'events': []}
            for url in (os.environ['ETL_GRAPHQL_URL'], os.environ['NARRATIVE_GRAPHQL_URL']):
                rejected = await client.post(url.rsplit('/', 1)[0] + '/demo/viewer-snapshots', json=metadata)
                assert rejected.status_code == 409, 'HTTP checkpoint unexpectedly accepted in broker mode'
            print('PASS both upstream HTTP checkpoint write paths disabled', flush=True)
        finally:
            # Resume the existing viewer's audience polling target, preserving state.
            state = (await client.get('http://backend:8000/lab/state')).json()
            if state['status'] != 'error':
                await transport.publish(build_snapshot(source, state['run_id'], state['position'],
                                                       finished=state['status'] == 'finished'))
            await runtime.close()
            await lab.close()
            with store.connect() as conn:
                conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(store.schema)))


if __name__ == '__main__':
    asyncio.run(main())
