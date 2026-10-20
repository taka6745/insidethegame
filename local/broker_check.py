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
from broker_probe import require_idle_replay


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
    supported = payload.data_reference['capabilities']['supported_event_types']
    for stat, event_type in (('cards', 'card'), ('corners', 'corner'), ('fouls', 'foul'),
                             ('offsides', 'offside'), ('throw_ins', 'throw_in'), ('saves', 'save')):
        actual = stats[f'all:{stat}']
        assert actual['available'] == (event_type in supported)
        counted = [e for e in events if e.event_type == event_type and not e.deleted]
        if stat == 'saves':  # Goalkeeper saves of on-target attempts, as ETL defines them.
            counted = [e for e in counted if not ({'defensiveBlock', 'fromShotOffTarget'} & set(e.qualifiers or {}))]
        expected_value = len(counted) if event_type in supported else None
        assert actual['value'] == expected_value, f'{stat} disagrees with observed events/coverage'
    assert (await etl.events(watermark, limit=100))['total'] == len(events)
    blocks = (await narrative.compact(watermark))['blocks']
    # Stoppage time repeats clock values across periods: contiguity and bounds are per period.
    assert all(a['end_seconds'] == b['start_seconds'] for a, b in zip(blocks, blocks[1:])
               if a.get('period') == b.get('period')), 'Recap blocks must be contiguous within a period'
    viewer = await narrative.read(watermark, 'viewer')
    position = (watermark.period or 0, watermark.clock_seconds or 0)
    assert all((row.get('period', position[0]), row['clock_seconds']) <= position for row in viewer['items']), \
        'A released narrative is later than the snapshot'
    assert watermark.id in seen, 'Waiting for narratives topic delivery'
    assert seen[watermark.id]['snapshot']['cursor'] == watermark.cursor
    return expected, len(viewer['items'])


async def main():
    etl_url = os.environ['ETL_GRAPHQL_URL']
    narrative_url = os.environ['NARRATIVE_GRAPHQL_URL']
    backend_url = os.getenv('BACKEND_URL', 'http://backend:8000')
    async with httpx.AsyncClient(timeout=30) as http:
        await require_idle_replay(http, backend_url)
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
                async def inspect_delivery(payload):
                    await require_idle_replay(http, backend_url)
                    if listener.done():
                        listener.result()
                    return await inspect(payload, etl, narrative, seen)
                try:
                    # Start, a duplicated first event, minute 1, just after half-time and full time.
                    half_time = next(i for i, e in enumerate(source.events) if e.event_type == 'period_end')
                    for minute in (0, None, 1, source.video_times[half_time] / 60 + 1, 'full'):
                        await require_idle_replay(http, backend_url)
                        cursor = 1 if minute is None else len(source.events) if minute == 'full' else next(
                            (i + 1 for i, t in enumerate(source.video_times) if t >= minute * 60), len(source.events)) if minute else 0
                        payload = await snapshot(source, run_id, cursor, 'finished' if minute == 'full' else 'ready')
                        event = payload.events[-1] if minute is None else None
                        await publish(producer, payload, event=event)
                        if minute is None:
                            # Same delivery twice must not inflate event history or standard totals.
                            await publish(producer, payload, event=event)
                        goals, count = await wait_for('ETL → narrative → Service Bus',
                            lambda: inspect_delivery(payload))
                        if listener.done():
                            listener.result()
                        label = 'first event + duplicate' if minute is None else 'full time' if minute == 'full' else f'{minute:.0f} playback min'
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
