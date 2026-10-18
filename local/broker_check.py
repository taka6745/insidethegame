"""Non-destructive broker integration: isolated run, real SDKs, owned GraphQL reads."""
import asyncio
import json
import os
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient
from azure.servicebus.aio import ServiceBusClient

from backend.adapters.question_data import GraphQLQuestionData
from backend.adapters.replay_source import FixtureEventSource
from backend.services.question_snapshot import LabSnapshotProvider


async def snapshot(source, run_id, cursor, status='ready'):
    lab = SimpleNamespace(_lock=asyncio.Lock(), source=source, run_id=run_id,
                          position=cursor, status=status)
    return await LabSnapshotProvider(lab).capture()


async def publish(producer, payload, *, event=None):
    body = {'type': 'MatchEvent', 'version': 1,
            'snapshot': payload.model_dump(mode='json', exclude={'events'}),
            'event': event.model_dump(mode='json') if event else None}
    body['snapshot']['events'] = []
    batch = await producer.create_batch(partition_key=payload.snapshot.match_id)
    batch.add(EventData(json.dumps(body)))
    await producer.send_batch(batch)


async def wait_for(label, operation, timeout=60):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return await operation()
        except (ValueError, AssertionError, httpx.HTTPError) as exc:
            last_error = exc
            await asyncio.sleep(.25)
    raise TimeoutError(f'{label} not ready after {timeout}s: {last_error}') from last_error


async def collect(receiver, run_id, seen):
    while True:
        for message in await receiver.receive_messages(max_message_count=100, max_wait_time=1):
            body = json.loads(str(message))
            if body.get('type') == 'BucketNarratives' and body.get('snapshot', {}).get('run_id') == run_id:
                assert body['version'] == 1
                assert isinstance(body['items'], list) and isinstance(body['events'], list)
                seen[body['snapshot']['id']] = body
            await receiver.complete_message(message)


async def inspect(payload, etl, narrative, seen):
    watermark, events = payload.snapshot, payload.events
    stats = {row['id']: row for row in (await etl.stats(watermark))['stats']}
    expected = sum(event.event_type == 'goal' and not event.deleted for event in events)
    assert stats['all:goals']['value'] == expected
    assert not stats['all:cards']['available'], 'Unrecorded cards cannot become false zeros'
    assert (await etl.events(watermark, limit=100))['total'] == len(events)
    blocks = (await narrative.compact(watermark))['blocks']
    assert all(a['end_seconds'] == b['start_seconds'] for a, b in zip(blocks, blocks[1:]))
    viewer = await narrative.read(watermark, 'viewer')
    assert all(row['clock_seconds'] <= (watermark.clock_seconds or 0) for row in viewer['items'])
    assert watermark.id in seen, 'Waiting for narratives topic delivery'
    assert seen[watermark.id]['snapshot']['cursor'] == watermark.cursor
    return expected, len(viewer['items'])


async def main():
    etl_url = os.environ['ETL_GRAPHQL_URL']
    narrative_url = os.environ['NARRATIVE_GRAPHQL_URL']
    backend_url = os.getenv('BACKEND_URL', 'http://backend:8000')
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(etl_url.rsplit('/', 1)[0] + '/demo/recording')
        response.raise_for_status()
        source = FixtureEventSource(content=response.content)
        etl, narrative = GraphQLQuestionData(etl_url), GraphQLQuestionData(narrative_url)
        run_id, seen = str(uuid4()), {}
        producer = EventHubProducerClient.from_connection_string(
            os.environ['MATCH_EVENTHUB_CONNECTION_STRING'],
            eventhub_name=os.getenv('MATCH_EVENTHUB_NAME', 'match-events'))
        bus = ServiceBusClient.from_connection_string(os.environ['NARRATIVE_SERVICEBUS_CONNECTION_STRING'])
        async with producer, bus:
            async with bus.get_subscription_receiver(topic_name='narratives', subscription_name='integration') as receiver:
                listener = asyncio.create_task(collect(receiver, run_id, seen))
                try:
                    for minute in (0, None, 1, 6, 12):
                        cursor = 1 if minute is None else next((i + 1 for i, t in enumerate(source.video_times)
                            if t >= minute * 60), len(source.events)) if minute else 0
                        payload = await snapshot(source, run_id, cursor, 'finished' if minute == 12 else 'ready')
                        event = payload.events[-1] if minute is None else None
                        await publish(producer, payload, event=event)
                        if minute is None:
                            # Same delivery twice must not inflate event history or standard totals.
                            await publish(producer, payload, event=event)
                        goals, count = await wait_for('ETL → narrative → Service Bus',
                            lambda: inspect(payload, etl, narrative, seen))
                        if listener.done():
                            listener.result()
                        label = 'first event + duplicate' if minute is None else f'{minute} playback min'
                        print(f'PASS {label}: {cursor} history events, {goals} goals, {count} narratives', flush=True)
                finally:
                    listener.cancel()
                    await asyncio.gather(listener, return_exceptions=True)
                    # Restore the live run as the audience-refresh target. This never resets or
                    # advances the user's replay; it republishes its current persisted watermark.
                    current = await http.get(backend_url + '/lab/state')
                    current.raise_for_status()
                    state = current.json()
                    if state['status'] != 'error':
                        payload = await snapshot(source, state['run_id'], state['position'], state['status'])
                        await publish(producer, payload)
        print('Broker check passed. Live replay position and viewer sessions were not changed.', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
