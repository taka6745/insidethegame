"""Local HTTP bridge → shared framing → persistent history → viewer WebSocket."""
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from websockets.sync.client import connect


def main():
    base = os.getenv('BACKEND_URL', 'http://backend:8000')
    upstream = os.getenv('FAKE_NARRATIVE_URL', 'http://fake-narrative:8000')
    document = json.loads((Path(__file__).parents[1] / 'fixtures/narratives/neutral.json').read_text())
    document['id'] = 'smoke-' + uuid4().hex
    with httpx.Client(timeout=900) as client:
        session = client.post(base + '/sessions', json={'profile_id': 'chelsea-analytical'})
        session.raise_for_status()
        path = '/sessions/' + session.json()['session_token']
        client.patch(base + path + '/preferences', json={'team': 'home', 'fan_style': 'analytical'}).raise_for_status()
        config = client.get(base + '/audiences').json()['config']
        buckets = [b for b in config['buckets'] if b['enabled']]
        if buckets:
            client.put(base + path + '/audience', json={'selections': buckets[0]['selections']}).raise_for_status()
        with connect(base.replace('http://', 'ws://') + path + '/live') as ws:
            ws.recv(timeout=10)
            response = client.post(upstream + '/neutral-narratives', json=document)
            response.raise_for_status()
            update = json.loads(ws.recv(timeout=10))
            assert update['reason'] == 'neutral_narrative_received'
            if buckets:
                current = next(n for n in update['data']['narratives'] if n['id'] == document['id'])
                assert current['bucket_id'] == buckets[0]['id'] and current['source'] == document
        duplicate = client.post(base + '/dev/neutral-narratives', json=document)
        duplicate.raise_for_status()
        assert duplicate.json()['generated'] == 0 and duplicate.json()['cached'] == len(buckets)
        cursor, found = None, False
        for _ in range(100):
            history = client.post(upstream + '/graphql', json={
                'query': 'query($after:String){neutralNarratives(matchId:"synthetic-demo",after:$after)}',
                'variables': {'after': cursor}}).json()['data']['neutralNarratives']
            found |= any(n['id'] == document['id'] for n in history['items'])
            cursor = history['next_cursor']
            if cursor is None or found:
                break
        assert found
    print('PASS: neutral source → configured shared DB buckets → persistent variants → matching live viewer; duplicate uses cache')


if __name__ == '__main__':
    main()
