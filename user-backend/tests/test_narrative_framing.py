import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import create_app
from backend.adapters.narratives import settle_narrative, NarrativeHistory
from backend.agents.narrative_framer import NarrativeFramer, FixtureNarrativeFramer
from backend.models.narratives import AudienceConfig, NeutralNarrative
from backend.repositories.narratives import NarrativeRepository
from backend.services.narratives import NarrativeService

ROOT = Path(__file__).parents[1] / 'fixtures/narratives'


def source(**changes):
    return NeutralNarrative(**(json.loads((ROOT / 'neutral.json').read_text()) | changes))


class RecordingModel:
    def __init__(self):
        self.calls = []
        self.fail_at = None

    async def complete(self, system, payload, **kwargs):
        self.calls.append(payload)
        if len(self.calls) == self.fail_at:
            return {'variants': []}
        return {'variants': [{'bucket_id': t['bucket_id'], 'text': payload['source']['text']}
                             for t in payload['audiences']]}


@pytest.fixture
def framing(store):
    store.initialize()
    repository = NarrativeRepository(store)
    repository.initialize()
    model = RecordingModel()
    service = NarrativeService(repository, NarrativeFramer(model), 'synthetic-demo')
    return service, model


def test_all_db_buckets_batched_without_viewers_and_duplicates_cached(framing):
    service, model = framing
    first = asyncio.run(service.receive(source()))
    assert first['generated'] == 12 and first['model_calls'] == 3
    assert len(model.calls) == 3
    assert model.calls[0]['audiences'][0]['layers'][0]['option']['description']
    assert asyncio.run(service.receive(source()))['cached'] == 12
    assert len(model.calls) == 3
    history = asyncio.run(service.history({'team': 'away', 'fan_style': 'casual'}))
    assert len(history['narratives']) == 1
    assert history['narratives'][0]['source'] == source().model_dump()


def test_partial_failure_retry_reuses_completed_batches(framing):
    service, model = framing
    model.fail_at = 2
    with pytest.raises(Exception, match='Framing did not validate'):
        asyncio.run(service.receive(source()))
    assert len(service.repository.cached(source())) == 4
    result = asyncio.run(service.receive(source()))
    assert result['generated'] == 8 and result['cached'] == 4
    assert len(model.calls) == 4


def test_content_conflict_revisions_and_late_redelivery(framing):
    service, model = framing
    asyncio.run(service.receive(source()))
    with pytest.raises(Exception, match='new narrative revision'):
        asyncio.run(service.receive(source(text='Changed')))
    asyncio.run(service.receive(source(revision=2, text='Corrected source')))
    assert asyncio.run(service.receive(source()))['status'] == 'superseded'
    history = asyncio.run(service.history({'team': 'home', 'fan_style': 'simple'}))
    assert [n['revision'] for n in history['narratives']] == [2]


def test_new_layer_option_and_smaller_demo_without_code_changes(framing):
    service, model = framing
    config, revision = service.repository.config()
    document = config.model_dump()
    document['layers'].append({'id': 'language', 'description': 'Output language', 'options': [
        {'id': 'english', 'description': 'Write in English'}, {'id': 'spanish', 'description': 'Write in Spanish'}]})
    document['buckets'] = [{'id': 'demo-spanish', 'selections': {
        'team': 'neutral', 'fan_style': 'simple', 'language': 'spanish'}}]
    new = AudienceConfig.model_validate(document)
    asyncio.run(service.configure(new, revision))
    result = asyncio.run(service.receive(source()))
    assert result['generated'] == 1 and result['model_calls'] == 1
    assert model.calls[0]['audiences'][0]['layers'][-1]['option']['description'] == 'Write in Spanish'
    with pytest.raises(Exception, match='Reload'):
        asyncio.run(service.configure(new, revision))


def test_description_change_invalidates_only_affected_variants(framing):
    service, model = framing
    asyncio.run(service.receive(source()))
    config, revision = service.repository.config()
    config.layers[0].options[0].description = 'Home support, explain calmly'
    asyncio.run(service.configure(config, revision))
    assert asyncio.run(service.history({'team': 'home', 'fan_style': 'simple'}))['narratives'] == []
    assert asyncio.run(service.receive(source()))['generated'] == 4
    assert len(model.calls) == 4


def test_configuration_validation():
    config = json.loads((ROOT / 'audiences.json').read_text())
    config['buckets'][0]['selections']['team'] = 'typo'
    with pytest.raises(ValidationError):
        AudienceConfig.model_validate(config)
    config['buckets'][0]['selections']['team'] = 'home'
    config['buckets'][1] = config['buckets'][0]
    with pytest.raises(ValidationError):
        AudienceConfig.model_validate(config)


def test_budget_rejects_instead_of_silently_skipping_buckets(framing):
    service, model = framing
    service.max_variants = 1
    with pytest.raises(Exception, match='exceed'):
        asyncio.run(service.receive(source()))
    assert not model.calls


def test_overlapping_delivery_has_one_owner(framing):
    service, model = framing
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        original = model.complete
        async def blocked(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        model.complete = blocked
        first = asyncio.create_task(service.receive(source()))
        await entered.wait()
        try:
            with pytest.raises(Exception, match='already being framed'):
                await service.receive(source())
        finally:
            release.set()
        await first
    asyncio.run(run())
    assert len(model.calls) == 3


def test_wrong_bucket_response_never_saved(framing):
    service, model = framing
    model.complete = AsyncMock(return_value={'variants': [{'bucket_id': 'wrong', 'text': 'Wrong'}]})
    with pytest.raises(Exception, match='did not validate'):
        asyncio.run(service.receive(source()))
    assert not service.repository.cached(source())


def test_session_live_routing_config_selection_and_restart(store, framing):
    service, model = framing
    with TestClient(create_app(store, narratives=service, enable_dev_feed=True)) as client:
        token = client.post('/sessions', json={'profile_id': 'chelsea-analytical'}).json()['session_token']
        path = f'/sessions/{token}'
        with client.websocket_connect(path + '/live') as ws:
            assert ws.receive_json()['data']['narratives'] == []
            result = client.post('/dev/neutral-narratives', json=source().model_dump())
            assert result.status_code == 202, result.text
            message = ws.receive_json()
            assert message['reason'] == 'neutral_narrative_received'
            assert message['data']['narratives'][0]['bucket_id'] == 'home-analytical'
        selected = client.put(path + '/audience', json={'selections': {'team': 'away', 'fan_style': 'simple'}})
        assert selected.status_code == 200
        assert selected.json()['narratives'][0]['bucket_id'] == 'away-simple'
        assert client.put(path + '/audience', json={'selections': {'team': 'missing'}}).status_code == 422
    with TestClient(create_app(store, narratives=service)) as restarted:
        state = restarted.post('/sessions', json={'profile_id': 'chelsea-analytical'}).json()['snapshot']
        assert state['narratives'][0]['bucket_id'] == 'away-simple'
        assert restarted.post('/dev/neutral-narratives', json=source().model_dump()).status_code == 404
    assert len(model.calls) == 3


def test_broker_settles_only_after_success_and_deadletters_invalid(framing):
    service, _ = framing
    receiver, notify = AsyncMock(), AsyncMock()
    asyncio.run(settle_narrative(receiver, source().model_dump_json(), service, notify))
    receiver.complete_message.assert_awaited_once()
    notify.assert_awaited_once()
    asyncio.run(settle_narrative(receiver, '{}', service, notify))
    receiver.dead_letter_message.assert_awaited_once()


def test_broker_retries_failed_framing(framing, monkeypatch):
    service, model = framing
    model.fail_at = 1
    receiver = AsyncMock()
    monkeypatch.setattr('backend.adapters.narratives.asyncio.sleep', AsyncMock())
    asyncio.run(settle_narrative(receiver, source().model_dump_json(), service, AsyncMock()))
    receiver.abandon_message.assert_awaited_once()
    receiver.complete_message.assert_not_awaited()


def test_history_replay_uses_same_cache(framing, monkeypatch):
    import httpx
    service, model = framing
    pages = [ {'items': [source().model_dump()], 'next_cursor': 'next'},
              {'items': [source().model_dump()], 'next_cursor': None} ]
    async def post(self, url, **kwargs):
        return httpx.Response(200, json={'data': {'neutralNarratives': pages.pop(0)}},
                              request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    assert asyncio.run(NarrativeHistory('http://fixture/graphql').replay(service)) == 2
    assert len(model.calls) == 3


def test_fixture_mode_is_explicit_and_makes_no_model_calls(framing):
    service, _ = framing
    service.framer = FixtureNarrativeFramer()
    result = asyncio.run(service.receive(source()))
    assert result['mode'] == 'fixture' and result['model_calls'] == 0


def test_dynamic_configuration_through_api_and_disabled_buckets(store, framing):
    service, model = framing
    with TestClient(create_app(store, narratives=service, enable_dev_feed=True)) as client:
        state = client.get('/audiences').json()
        document = state['config']
        document['layers'].append({'id': 'language', 'description': 'Language',
                                  'options': [{'id': 'english', 'description': 'Use English'}]})
        for bucket in document['buckets']:
            bucket['selections']['language'] = 'english'
            bucket['enabled'] = bucket['id'] == 'home-simple'
        body = {'config': document, 'expected_revision': state['revision']}
        assert client.put('/dev/audiences', json=body).status_code == 200
        assert client.put('/dev/audiences', json=body).status_code == 409
        session = client.post('/sessions', json={'profile_id': 'chelsea-analytical'}).json()
        assert session['snapshot']['audience']['status'] == 'unconfigured'
        path = '/sessions/' + session['session_token'] + '/audience'
        assert client.put(path, json={'selections': {
            'team': 'away', 'fan_style': 'simple', 'language': 'english'}}).status_code == 422
        response = client.put(path, json={'selections': {
            'team': 'home', 'fan_style': 'simple', 'language': 'english'}})
        assert response.json()['bucket'] == 'home:simple'
        result = client.post('/dev/neutral-narratives', json=source().model_dump()).json()
        assert result['generated'] == 1
        document['buckets'][0]['enabled'] = False
        assert client.put('/dev/audiences', json={'config': document, 'expected_revision': 2}).status_code == 200
        assert client.post('/dev/neutral-narratives', json=source(id='paused').model_dump()).json()['status'] == 'paused'
    assert len(model.calls) == 1


def test_timeout_releases_delivery_lease_and_can_retry(framing):
    service, model = framing
    async def stalled(*args, **kwargs):
        await asyncio.sleep(60)
    original = model.complete
    model.complete = stalled
    service.timeout = 0.01
    with pytest.raises(Exception, match='did not validate'):
        asyncio.run(service.receive(source()))
    model.complete = original
    service.timeout = 60
    assert asyncio.run(service.receive(source()))['generated'] == 12


def test_narrative_agent_uses_framework_and_separate_output_budget(monkeypatch):
    import httpx
    from agent_framework import Agent
    from backend.adapters.llm import LocalJsonModel
    invoked, requests = [], []
    original = Agent.run
    def run(self, *args, **kwargs):
        invoked.append(self.name)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Agent, 'run', run)
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0,
            'model': 'development-model', 'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': json.dumps({'variants': [
                {'bucket_id': 'home-simple', 'text': source().text}]})}}]})
    model = LocalJsonModel('http://local.invalid/v1', 'development-model', name='shared_narrative_framer',
                          max_output_tokens=6000, transport=httpx.MockTransport(respond))
    response = asyncio.run(NarrativeFramer(model).frame(source(), [{'bucket_id': 'home-simple', 'layers': []}]))
    assert response.variants[0].bucket_id == 'home-simple'
    assert invoked == ['shared_narrative_framer']
    assert requests[0].get('max_tokens', requests[0].get('max_completion_tokens')) == 6000
    assert LocalJsonModel('http://local.invalid/v1', 'development-model').max_output_tokens == 3000
