"""Viewer session and narrative helpers shared by the product, follow and multi-match tests."""
from uuid import uuid4

from backend.models.engine_narratives import EngineNarrative
from harness import MATCH

OTHER = 'north-south-0badc0de'
VIEWER = '00000000-0000-4000-8000-000000000001'  # one browser's random viewer id


def start(client, match_id=MATCH, profile='riverton-analytical'):
    response = client.post(f'/product/matches/{match_id}/sessions', json={'profile_id': profile, 'viewer_id': VIEWER})
    assert response.status_code == 200, response.text
    return response.json()


def path(token, match_id=MATCH):
    return f'/product/matches/{match_id}/sessions/{token}'


def ask(client, token, text, match_id=MATCH):
    response = client.post(path(token, match_id) + '/messages', json={'prompt': text, 'request_id': str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()


def narrative(match_id, bucket='home:analytical', seq=1, minute=0, second=30, event_seq=None, text='Kick-off.', period=1):
    return EngineNarrative.model_validate({
        'id': f'narr:{match_id}:{bucket}:{seq}', 'matchId': match_id, 'userType': bucket, 'seq': seq,
        'stepId': f'{match_id}:step:{seq}', 'trigger': {'type': 'keyEvent', 'ref': 'k', 'reason': 'r'},
        'matchTime': {'periodId': period, 'timeMin': minute}, 'text': text, 'createdAt': f'2026-10-20T00:00:{seq:02d}Z',
        'timeSec': second, 'eventSeq': event_seq, 'model': 'never-stored'})


def deliver(run, item):
    return run.client.portal.call(run.app.state.product.narrative, item)


def until(ws, check, limit=20):
    """The first pushed snapshot satisfying check; earlier queued updates may arrive first."""
    for _ in range(limit):
        message = ws.receive_json()
        if check(message):
            return message
    raise AssertionError('No matching update')


def refresh(run, match_id=MATCH):
    async def go():
        await run.app.state.product.projection(match_id).refresh()
    run.client.portal.call(go)


def follow(client, token, spec, match_id=MATCH):
    return client.post(path(token, match_id) + '/follows', json={'spec': spec})


def follow_narrative(match_id=MATCH, bucket='home:analytical', seq=1, text='Insight.', topic=None, event_seq=1):
    kind = {'kind': 'subscription', 'topicId': topic} if topic else {}
    return EngineNarrative.model_validate({
        'id': f"{'sub' if topic else 'narr'}:{match_id}:{topic or ''}:{bucket}:{seq}", 'matchId': match_id,
        'userType': bucket, 'seq': seq, 'stepId': f'{match_id}:step:{seq}',
        'trigger': {'type': 'scheduled', 'ref': 'r', 'reason': 'r'}, 'matchTime': {'periodId': 1, 'timeMin': 0},
        'text': text, 'createdAt': f'2026-10-20T00:00:{seq:02d}Z', 'timeSec': 30, 'eventSeq': event_seq, **kind})


def view(run, token, match_id=MATCH):
    async def go():
        await run.app.state.product.projection(match_id).refresh()
    run.client.portal.call(go)
    return run.client.get(path(token, match_id)).json()['snapshot']
