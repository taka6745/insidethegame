"""Non-destructive cross-service checkpoint check; no live replay/session reset."""
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import uuid4
import httpx
from backend.adapters.replay_source import FixtureEventSource
from backend.adapters.question_data import GraphQLQuestionData
from backend.models.questions import MatchSnapshot, SnapshotInput


async def main():
    etl_url, narrative_url = os.environ['ETL_GRAPHQL_URL'], os.environ['NARRATIVE_GRAPHQL_URL']
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(etl_url.rsplit('/',1)[0] + '/demo/recording')
        response.raise_for_status()
    source = FixtureEventSource(content=response.content)
    etl = GraphQLQuestionData(etl_url, bridge='demo')
    narrative = GraphQLQuestionData(narrative_url, bridge='demo')
    run = str(uuid4())
    half_time = next(i for i, e in enumerate(source.events) if e.event_type == 'period_end')
    for minute in (0, 1, source.video_times[half_time] / 60 + 1, 'full'):
        cursor = len(source.events) if minute == 'full' else next(
            (i + 1 for i,t in enumerate(source.video_times) if t >= minute * 60), len(source.events)) if minute else 0
        events = list(source.history(cursor))
        latest = events[-1] if events else None
        snapshot = MatchSnapshot(id='',run_id=run,match_id=source.match_id,recording_hash=source.fingerprint,
            cursor=cursor,clock_seconds=latest.match_time_seconds if latest else None,
            period=latest.period if latest else None,captured_at=datetime.now(timezone.utc).isoformat())
        payload = SnapshotInput(snapshot=snapshot,events=events,teams=source.spec['teams'],players=source.spec['players'],data_reference=source.data_reference())
        data = payload.model_dump(mode='json'); data['snapshot'].pop('id'); data['snapshot'].pop('captured_at')
        snapshot.id = hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        await etl.capture(payload, purpose='viewer')
        await narrative.capture(payload, purpose='viewer')
        stats = {s['id']:s for s in (await etl.stats(snapshot))['stats']}
        expected = sum(e.event_type == 'goal' and not e.deleted for e in events)
        assert stats['all:goals']['value'] == expected
        assert stats['all:cards']['available'] == ('card' in source.data_reference()['capabilities']['supported_event_types'])
        page = await etl.events(snapshot,limit=100)
        assert page['total'] == len(events)
        compact = await narrative.compact(snapshot)
        blocks = compact['blocks']
        assert all(a['end_seconds'] == b['start_seconds'] for a,b in zip(blocks,blocks[1:]))
        viewer = await narrative.read(snapshot,'viewer')
        assert all(row['clock_seconds'] <= (snapshot.clock_seconds or 0) for row in viewer['items'])
        print(f'{minute:2} playback min: {len(events)} events, {expected} goals, {len(viewer["items"])} enabled narratives; history/stats/recaps agree')
    print('Cross-service GRF demo check passed. Live session and replay position unchanged.')


asyncio.run(main())
