"""Non-destructive pipeline probe: Event Hubs → etl-stream → SQL → ETL GraphQL (DAB) and the backend.

Sends a synthetic probe match under a fresh matchId (MA1, 10 MatchEvent v2 with a duplicate, POS
samples; no MA3, so no notifications reach the engine and no SPADL actions exist), checks DAB's matches,
matchWatermarks and executeStatsAtSeq (one row per enabled statDefinitions kind and scope, once the SPADL
post-processor caught up; possession from POS) and that the backend lists the match, then purges the
probe from every owner and checks nothing of it is left. Live matches are untouched."""
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient

from demo_control import CONSUMERS, OWNER
from settings import ETL_GRAPHQL

DAB = os.getenv('ETL_GRAPHQL_URL', ETL_GRAPHQL)
BACKEND = OWNER['backend'].url
KINDS = ['kick_off', 'pass', 'pass', 'shot', 'pass', 'goal', 'kick_off', 'pass', 'foul', 'pass']
QUERY = '''query ($m: String!, $s: Int!) {
  matches(filter: {matchId: {eq: $m}}) { items { matchId status fixture teams { items { contestantId } } } }
  matchWatermarks(filter: {matchId: {eq: $m}}) { items { seq } }
  rawEvents(filter: {matchId: {eq: $m}}) { items { id } }
  possessionSamples(filter: {matchId: {eq: $m}}) { items { sampleId } }
  executeStatsAtSeq(matchId: $m, seq: $s) { statId value available }
  statDefinitions(filter: {enabled: {eq: true}}, first: 1000) { items { statId } } }'''


def stamp(t):
    return t.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def messages(match_id):
    kickoff = datetime.now(timezone.utc)
    yield {'feed': 'MA1', 'schemaVersion': 1, 'matchId': match_id, 'synthetic': True, 'fixture': 'broker-check',
           'sourceMatchId': 'broker-check', 'runId': str(uuid4()), 'description': 'SYNTHETIC pipeline probe',
           'scheduledKickoff': stamp(kickoff), 'timeStamp': stamp(kickoff - timedelta(seconds=1)),
           'capabilities': {'canonicalEvents': True, 'possessionSamples': True, 'video': False, 'periods': 2,
                            'eventTypes': sorted(set(KINDS)), 'shotOutcomes': True, 'bodyParts': False},
           'contestant': [{'id': 'probe-home', 'name': 'Probe Home', 'position': 'home', 'lineup': []},
                          {'id': 'probe-away', 'name': 'Probe Away', 'position': 'away', 'lineup': []}]}
    for seq, kind in enumerate(KINDS, 1):
        team = 'probe-home' if seq < 7 else 'probe-away'
        at = stamp(kickoff + timedelta(seconds=seq))
        yield {'feed': 'POS', 'schemaVersion': 1, 'matchId': match_id, 'synthetic': True, 'sampleId': seq,
               'periodId': 1, 'videoSeconds': float(seq), 'durationSeconds': 1.0, 'contestantId': team,
               'eventSeq': seq - 1, 'timeStamp': at}
        yield {'type': 'MatchEvent', 'version': 2, 'matchId': match_id, 'seq': seq, 'timeStamp': at,
               'synthetic': True, 'event': {
                   'event_id': f'probe-{seq}', 'match_id': match_id, 'revision': 1, 'event_type': kind,
                   'team_id': team, 'player_id': None, 'body_part': None, 'period': 1, 'match_time_seconds': seq,
                   'outcome': 'on_target' if kind == 'shot' else None, 'distance_metres': None, 'deleted': False,
                   'sequence': seq, 'video_seconds': float(seq), 'x': 50.0, 'y': 50.0, 'possession_id': 1,
                   'qualifiers': {}}}


async def read(http, match_id, seq):
    response = await http.post(DAB, json={'query': QUERY, 'variables': {'m': match_id, 's': seq}})
    response.raise_for_status()
    body = response.json()
    assert not body.get('errors'), body.get('errors')
    return body['data']


async def until(label, check, timeout=60):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return await check()
        except (AssertionError, httpx.HTTPError, KeyError, IndexError) as exc:
            if time.monotonic() > deadline:
                raise TimeoutError(f'{label} not ready after {timeout}s: {exc!r}') from exc
            await asyncio.sleep(.5)


async def main():
    match_id = 'broker-check-' + uuid4().hex[:8]
    sent = list(messages(match_id))
    async with httpx.AsyncClient(timeout=20) as http:
        try:
            async with EventHubProducerClient.from_connection_string(
                    os.environ['MATCH_EVENTHUB_CONNECTION_STRING'],
                    eventhub_name=os.getenv('MATCH_EVENTHUB_NAME', 'match-events')) as producer:
                batch = await producer.create_batch(partition_key=match_id)
                for message in [*sent, sent[-1]]:  # The final event is delivered twice.
                    batch.add(EventData(json.dumps(message)))
                await producer.send_batch(batch)

            async def committed():
                data = await read(http, match_id, len(KINDS))
                assert data['matchWatermarks']['items'][0]['seq'] == len(KINDS)
                return data
            data = await until('ETL watermark', committed)
            match = data['matches']['items'][0]
            assert match['fixture'] == 'broker-check' and len(match['teams']['items']) == 2
            # Served only once the SPADL post-processor reached the watermark: every enabled kind for all, home, away.
            kinds = len(data['statDefinitions']['items'])

            async def converted():
                rows = (await read(http, match_id, len(KINDS)))['executeStatsAtSeq']
                assert kinds and len(rows) == 3 * kinds, (len(rows), kinds)
                return {row['statId']: row for row in rows}
            stats = await until('SPADL post-processor', converted)
            # No MA3, so no SPADL actions: counts are 0; possession comes from POS.
            assert stats['all:goals']['value'] == 0 and stats['all:passes']['value'] == 0
            assert stats['probe-home:possession']['value'] == 60.0
            assert (await read(http, match_id, len(KINDS) + 1))['executeStatsAtSeq'] == []  # Past the watermark.
            print(f'PASS Event Hubs → etl-stream → SQL → SPADL → DAB: {match_id} at seq {len(KINDS)}, duplicate '
                  f'ignored, {len(stats)} stats served', flush=True)

            async def listed():
                response = await http.get(BACKEND + '/product/matches')
                response.raise_for_status()
                assert match_id in [m['match_id'] for m in response.json()]
            await until('backend match list', listed)
            print('PASS backend lists the probe match from its MA1', flush=True)
        finally:
            for owner in CONSUMERS:  # The probe's MA1 reached every consumer of the hub.
                (await http.post(owner.url + '/admin/matches/purge', json={'match_id': match_id},
                                 headers=owner.headers)).raise_for_status()
        data = await read(http, match_id, len(KINDS))
        left = {k: len(v['items']) for k, v in data.items() if k not in ('executeStatsAtSeq', 'statDefinitions')}
        assert not any(left.values()) and data['executeStatsAtSeq'] == [], left
        response = await http.get(BACKEND + '/product/matches')
        assert match_id not in [m['match_id'] for m in response.json()]
        print('PASS probe purged from ETL, engine and backend; no rows left', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
