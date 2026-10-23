"""Viewer choices persist per (profile, match) and pick narratives; only configuration enables targets."""
import pytest

from harness import MATCH, Running, Upstream
from starlette.websockets import WebSocketDisconnect

from support import OTHER, ask, deliver, narrative, path, refresh, start, until

TEMPLATE = '/dev/fixtures/riverton-madrid/audience-config'
DEMO_BUCKETS = {'home:analytical', 'away:casual', 'neutral:simple'}


def select(client, token, bucket_id='away:casual', match_id=MATCH):
    response = client.put(path(token, match_id) + '/audience', json={'bucket_id': bucket_id})
    assert response.status_code == 200, response.text
    return response.json()


def enabled(client, match_id=MATCH):
    body = client.get(f'/matches/{match_id}/audience-config').json()
    assert len(body['buckets']) == 24  # 12 audiences, each Standard and (disabled) Brief length
    assert {b['id'] for b in body['buckets'] if b['enabled']} == {t['bucket_id'] for t in body['generation_targets']}
    return {t['bucket_id'] for t in body['generation_targets']}


def configure(client, bucket_ids):
    body = client.get(TEMPLATE).json()
    for bucket in body['config']['buckets']:
        bucket['enabled'] = bucket['id'] in bucket_ids
    response = client.put(TEMPLATE, json={'expected_revision': body['revision'], 'config': body['config']})
    assert response.status_code == 200, response.text


def test_every_enabled_bucket_reroutes_feed_and_cards_without_changing_account_or_targets(store):
    with Running(store) as run:
        everything = [f'{t}:{s}' for t in ('home', 'away', 'neutral') for s in ('simple', 'casual', 'experienced', 'analytical')]
        configure(run.client, everything)
        data = start(run.client)
        token = data['session_token']
        # Labels come from the template: `{home}`/`{away}` become this match's team names.
        assert data['snapshot']['audience_buckets'][:2] == [
            {'id': 'home:simple', 'label': 'Riverton Rovers · Simple'}, {'id': 'home:casual', 'label': 'Riverton Rovers · Casual'}]
        assert len(data['snapshot']['audience_buckets']) == 12
        profiles = run.service.repository.profiles()
        tag = run.client.get(f'/matches/{MATCH}/audience-config').headers['etag']
        run.send(35)
        for seq, bucket in enumerate(everything, 1):
            deliver(run, narrative(MATCH, bucket=bucket, seq=seq, event_seq=35, text=bucket))
        refresh(run)
        version = 0
        with run.client.websocket_connect(path(token) + '/live') as ws:
            ws.receive_json()
            for bucket in everything:
                team, style = bucket.split(':')
                snapshot = select(run.client, token, bucket)['snapshot']
                assert snapshot['audience'] == {'bucket_id': bucket, 'selections': {'team': team, 'fan_style': style,
                                                                                       'length': 'standard'}}
                support = {'home': 'riverton', 'away': 'madrid', 'neutral': 'neutral'}[team]
                assert snapshot['bucket_id'] == bucket and snapshot['profile']['team'] == support
                assert snapshot['version'] > version
                version = snapshot['version']
                assert [n['text'] for n in snapshot['narratives']] == [bucket]
                assert all(card['id'].startswith(('all' if team == 'neutral' else support) + ':') for card in snapshot['cards'])
                while (pushed := ws.receive_json())['version'] < snapshot['version']:
                    pass  # An earlier projection update may still be queued.
                assert pushed['audience'] == snapshot['audience']
        # Watching and choosing never change what the engine generates.
        assert run.client.get(f'/matches/{MATCH}/audience-config', headers={'If-None-Match': tag}).status_code == 304
        assert run.service.repository.profiles() == profiles


def test_choice_preserves_chat_pins_and_survives_takeover_and_restart(store):
    upstream = Upstream()
    with Running(store, upstream=upstream) as run:
        token = start(run.client)['session_token']
        offer = ask(run.client, token, 'how many Both teams shots')['offers'][0]
        assert run.client.post(path(token) + f'/offers/{offer["id"]}/track').status_code == 200
        before = run.client.get(path(token)).json()
        selected = select(run.client, token)
        assert selected['turns'] == before['turns'] and selected['offers'] == before['offers']
        assert selected['snapshot']['cards'][-1]['pin_id'] == 'standard:all:shots'
        takeover = start(run.client)
        assert takeover['audience'] == selected['audience'] and takeover['turns'] == before['turns']
        assert run.client.get(path(token)).status_code == 409
        token = takeover['session_token']
    with Running(store, upstream=upstream, matches=()) as run:
        restored = run.client.get(path(token)).json()
        assert restored['audience'] == selected['audience'] and restored['snapshot']['cards'][-1]['pinned']
        assert enabled(run.client) == DEMO_BUCKETS


@pytest.mark.parametrize('body', [
    {'bucket_id': 'riverton:simple'}, {'bucket_id': 'away:simple'},  # Unknown; configured but disabled.
    {'team': 'home', 'fan_style': 'simple'}, {}, {'bucket_id': 'home:analytical', 'enabled': True}])
def test_invalid_choices_never_write(store, body):
    with Running(store) as run:
        data = start(run.client)
        before = run.client.get(f'/matches/{MATCH}/audience-config').json()
        assert run.client.put(path(data['session_token']) + '/audience', json=body).status_code == 422
        assert run.client.get(path(data['session_token'])).json()['audience'] == data['audience']
        assert run.client.get(f'/matches/{MATCH}/audience-config').json() == before


def test_defaults_follow_the_account_and_a_disabled_choice_falls_back(store):
    with Running(store, matches=(MATCH, OTHER)) as run:
        assert start(run.client)['audience']['bucket_id'] == 'home:analytical'
        assert start(run.client, OTHER, profile='united-casual')['audience']['bucket_id'] == 'away:casual'
        token = start(run.client, profile='neutral-simple')['session_token']
        assert select(run.client, token, 'away:casual')['audience']['bucket_id'] == 'away:casual'
        configure(run.client, {'home:analytical', 'neutral:simple'})
        view = run.client.get(path(token)).json()
        assert view['audience']['bucket_id'] == 'neutral:simple'  # The account default again.
        assert [b['id'] for b in view['snapshot']['audience_buckets']] == ['home:analytical', 'neutral:simple']
        configure(run.client, {'home:analytical'})
        assert run.client.get(path(token)).json()['audience']['bucket_id'] == 'home:analytical'  # First enabled.


def test_a_template_edit_reaches_connected_viewers(store):
    with Running(store) as run:
        token = start(run.client)['session_token']  # home:analytical
        with run.client.websocket_connect(path(token) + '/live') as ws:
            ws.receive_json()
            configure(run.client, DEMO_BUCKETS | {'home:simple'})  # New choice: pushed without any event.
            pushed = until(ws, lambda m: len(m['audience_buckets']) == 4)
            assert pushed['audience']['bucket_id'] == 'home:analytical'
            configure(run.client, {'home:simple', 'neutral:simple'})  # The viewer's bucket went: reconnect.
            with pytest.raises(WebSocketDisconnect) as exc:
                until(ws, lambda m: False)
            assert exc.value.code == 1013
        with run.client.websocket_connect(path(token) + '/live') as ws:
            assert ws.receive_json()['audience']['bucket_id'] == 'home:simple'


def test_no_enabled_bucket_shows_no_narratives(store):
    with Running(store) as run:
        configure(run.client, set())
        run.send(5)
        deliver(run, narrative(MATCH, event_seq=5))
        refresh(run)
        snapshot = start(run.client)['snapshot']
        assert snapshot['audience'] is None and snapshot['audience_buckets'] == [] and snapshot['narratives'] == []
        assert enabled(run.client) == set()


def test_question_agent_uses_match_audience_override(store):
    from backend.models.questions import QuestionDraft
    seen = []

    class Profile:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            seen.append(context['profile'])
            return QuestionDraft(answer_kind='match', status='answer', text='ok')
    with Running(store, agent=Profile()) as run:
        token = start(run.client)['session_token']
        select(run.client, token, 'neutral:simple')
        ask(run.client, token, 'how is it going')
        assert seen == [{'team': 'neutral', 'fan_style': 'simple', 'length': 'standard'}]
