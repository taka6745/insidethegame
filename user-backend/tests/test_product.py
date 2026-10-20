"""Product flow: a shared upstream view and isolated durable viewer pins."""
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from backend.app import create_app
from test_questions import build


def product(store):
    lab, questions, upstreams, _ = build(store)
    return lab, questions, upstreams, create_app(store, lab=lab, questions=questions, enable_product=True)


def start(client, profile='chelsea-analytical'):
    response = client.post('/product/sessions', json={'profile_id': profile})
    assert response.status_code == 200, response.text
    return response.json()


def ask(client, token, text):
    response = client.post(f'/product/{token}/messages', json={'prompt': text, 'request_id': str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()


def test_product_uses_same_match_and_maps_relative_profile(store):
    lab, _, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
        snapshot = data['snapshot']
        assert snapshot['match']['id'] == data['match_id'] == lab.source.match_id
        assert snapshot['bucket'] == 'chelsea:analytical'
        assert [c['id'] for c in snapshot['cards']] == ['chelsea:goals', 'chelsea:shots', 'chelsea:corners', 'chelsea:passes', 'chelsea:cards']
        assert all(c['value'] == 0 for c in snapshot['cards'])
        profiles = client.get('/product/profiles').json()['profiles']
        away = next(p for p in profiles if p['id'] == 'united-casual')
        assert away['team'] == 'madrid' and 'Madrid' in away['display_name']
        reply = ask(client, data['session_token'], 'what is offside')
        assert reply['snapshot']['run_id'] == data['run_id']


def test_all_five_standard_values_are_passed_through_from_etl(store):
    _, questions, _, app = product(store)
    original = questions.match_data.stats

    async def supplied_values(snapshot):
        result = await original(snapshot)
        for index, stat in enumerate(result['stats']):
            stat['value'] = 1000 + index
        return result

    async def no_event_search(*args, **kwargs):
        raise AssertionError('Standard cards must not search event history')

    questions.match_data.stats = supplied_values
    questions.match_data.events = no_event_search
    with TestClient(app) as client:
        data = start(client)
        supplied = {stat['id']: stat['value'] for stat in app.state.product.shared['stats']}
        assert len(data['snapshot']['cards']) == 5
        assert all(card['value'] == supplied[card['id']] >= 1000
                   for card in data['snapshot']['cards'])
        restored = client.get(f'/product/{data["session_token"]}').json()
        assert restored['snapshot']['cards'] == data['snapshot']['cards']


def test_pins_are_durable_private_and_restore_standard_slot(store):
    lab, _, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
        token = data['session_token']
        reply = ask(client, token, "Track Mbappe's headed shots")
        offer = reply['offers'][0]
        response = client.post(f'/product/{token}/offers/{offer["id"]}/track').json()
        calculation = response['calculation']['id']
        assert [c['kind'] for c in response['snapshot']['cards']] == ['standard'] * 4 + ['custom']
        assert response['snapshot']['cards'][-1]['value'] == 0
        assert [c['id'] for c in response['snapshot']['cards'][:-1]] == [
            'chelsea:goals', 'chelsea:shots', 'chelsea:corners', 'chelsea:passes']
        for _ in range(len(lab.source.events)):
            client.portal.call(lab.advance)
        client.portal.call(app.state.product.refresh)
        restored = client.get(f'/product/{token}').json()
        assert restored['snapshot']['cards'][-1]['value'] == 3
        assert restored['turns'][0]['reply']['offers'][0]['value'] == 0
        other = start(client, 'neutral-simple')
        assert all(c['kind'] == 'standard' for c in other['snapshot']['cards'])
        assert client.post(f'/product/{other["session_token"]}/offers/{offer["id"]}/track').status_code == 404
        restored = start(client)
        assert restored['snapshot']['cards'][-1]['id'] == calculation
        unpin = client.delete(f'/product/{restored["session_token"]}/pins/{calculation}').json()
        assert len(unpin['snapshot']['cards']) == 5
        assert all(c['kind'] == 'standard' for c in unpin['snapshot']['cards'])


def test_socket_push_and_takeover_without_polling(store):
    lab, _, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
        token = data['session_token']
        with client.websocket_connect(f'/product/{token}/live') as ws:
            initial = ws.receive_json()
            assert initial['match']['position'] == 0
            client.portal.call(lab.advance)
            updated = ws.receive_json()
            assert updated['match']['position'] == 1
            assert updated['version'] > initial['version']
            # Even the separate lab UI uses the same takeover boundary.
            client.post('/lab/chat/sessions', json={'profile_id': 'chelsea-analytical'})
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4001
        assert not app.state.product.live.peers


def test_projection_work_shared_and_corrections_remove_retracted_goal(store):
    lab, questions, upstreams, app = product(store)
    with TestClient(app) as client:
        first = start(client)
        second = start(client, 'neutral-simple')
        reads = []
        original = questions.match_data.stats
        async def count(snapshot):
            reads.append(snapshot.cursor)
            return await original(snapshot)
        questions.match_data.stats = count
        with client.websocket_connect(f'/product/{first["session_token"]}/live') as a, client.websocket_connect(f'/product/{second["session_token"]}/live') as b:
            a.receive_json(); b.receive_json()
            client.portal.call(lab.advance)
            assert a.receive_json()['match']['position'] == b.receive_json()['match']['position'] == 1
            assert reads == [1]
        for _ in range(1, len(lab.source.events)):
            client.portal.call(lab.advance)
        client.portal.call(app.state.product.refresh)
        view = client.get(f'/product/{first["session_token"]}').json()['snapshot']
        assert [t['score'] for t in view['match']['teams']] == [1, 0]
        assert not any(e['deleted'] for e in view['events'])
        assert all('chelsea:analytical' in n['buckets'] for n in view['narratives'])
        assert all(len(upstream.state.question_data.snapshots) == 0 for upstream in upstreams)
        assert all(len(upstream.state.question_data.viewer_snapshots) <= 2 for upstream in upstreams)


def test_reset_closes_old_run_and_new_session_gets_clean_snapshot(store):
    lab, _, _, app = product(store)
    with TestClient(app) as client:
        first = start(client)
        token = first['session_token']
        with client.websocket_connect(f'/product/{token}/live') as ws:
            ws.receive_json()
            client.post('/lab/reset')
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4001
        second = start(client)
        assert second['run_id'] != first['run_id']
        assert second['snapshot']['match']['position'] == 0
        assert second['snapshot']['events'] == []
        assert second['turns'] == []


def test_product_pin_limit_and_duplicate_tracking(store):
    from backend.models.rules import Rule
    lab, questions, _, app = product(store)
    with TestClient(app) as client:
        token = start(client)['session_token']
        # Valid offers from deterministic calculation, independent of model wording.
        offers = []
        for i, kind in enumerate(('pass','shot','corner','save','tackle','clearance')):
            rule = Rule.model_validate({'match_id': lab.source.match_id, 'operation': 'count',
                'predicates': [{'field': 'event_type', 'op': 'eq', 'value': kind}]})
            turn = questions.repository.begin(token, uuid4(), f'Test {i}')
            offer = {'id': str(uuid4()), 'run_id': str(lab.run_id), 'rule': rule.model_dump(mode='json'),
                     'label': kind, 'value': 0}
            questions.repository.finish(token, turn['id'], {'status':'answer','text': kind,'offers':[offer]})
            offers.append(offer)
        for offer in offers[:5]:
            response = client.post(f'/product/{token}/offers/{offer["id"]}/track')
            assert response.status_code == 200, response.text
        assert client.post(f'/product/{token}/offers/{offers[0]["id"]}/track').status_code == 200
        sixth = client.post(f'/product/{token}/offers/{offers[5]["id"]}/track')
        assert sixth.status_code == 409 and sixth.json()['code'] == 'cards_full'
        assert lab.engine.count == 5


def test_viewer_projection_does_not_evict_question_snapshot(store):
    lab, questions, upstreams, app = product(store)
    with TestClient(app) as client:
        token = start(client)['session_token']
        reply = ask(client, token, 'what is offside')
        snapshot_id = reply['snapshot']['id']
        for _ in range(20):
            client.portal.call(lab.advance)
            client.portal.call(app.state.product.refresh)
        assert all(snapshot_id in upstream.state.question_data.snapshots for upstream in upstreams)


def test_upstream_audience_style_and_period_are_preserved(store):
    lab, _, _, app = product(store)
    with TestClient(app) as client:
        analyst = start(client)
        simple = start(client, 'neutral-simple')
        for _ in range(10):
            client.portal.call(lab.advance)
        client.portal.call(app.state.product.refresh)
        a = client.get(f'/product/{analyst["session_token"]}').json()['snapshot']
        b = client.get(f'/product/{simple["session_token"]}').json()['snapshot']
        assert a['narratives'][-1]['text'] != b['narratives'][-1]['text']
        assert a['narratives'] == [n for n in app.state.product.shared['narratives']
                                   if 'chelsea:analytical' in n['buckets']]
        assert a['narratives'][-1]['period'] == b['narratives'][-1]['period'] == 2
        assert [c['id'] for c in a['cards']] == ['chelsea:shots', 'chelsea:corners', 'chelsea:passes', 'chelsea:goals', 'chelsea:cards']
        assert [c['id'] for c in b['cards']] == ['all:goals', 'all:cards', 'all:shots', 'all:corners', 'all:passes']


def test_projection_failure_invalidates_live_cache(store):
    lab, questions, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
        async def unavailable(*args, **kwargs):
            raise RuntimeError('upstream unavailable')
        questions.match_data.stats = unavailable
        with client.websocket_connect(f'/product/{data["session_token"]}/live') as ws:
            ws.receive_json()
            client.portal.call(lab.advance)
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 1013
        assert app.state.product.shared is None


def test_lab_takeover_cannot_race_product_socket_attachment(store):
    import asyncio
    lab, questions, _, app = product(store)
    with TestClient(app) as client:
        token = start(client)['session_token']
        service = app.state.product
        original = service.bootstrap
        async def interleave():
            validated, release = asyncio.Event(), asyncio.Event()
            async def pause(token):
                result = await original(token)
                validated.set()
                await release.wait()
                return result
            service.bootstrap = pause
            attaching = asyncio.create_task(service.attach(token))
            await validated.wait()
            replacing = asyncio.create_task(questions.start('chelsea-analytical'))
            await asyncio.sleep(0)
            assert not replacing.done()
            release.set()
            peer, _ = await attaching
            await replacing
            assert peer.closing
            assert (await peer.queue.get())['close'] == 4001
            service.live.detach(peer)
        client.portal.call(interleave)


def test_epl_demo_is_explicit_same_match_and_lab_default_is_preserved(store):
    lab, _, _, app = product(store)
    with TestClient(app) as client:
        original = lab.source.fingerprint
        selected = client.post('/product/demo/reset')
        assert selected.status_code == 200, selected.text
        assert selected.json()['scenario']['match_id'] == 'product-demo-match'
        assert lab.source.fingerprint != original
        data = start(client)
        assert [t['name'] for t in data['snapshot']['match']['teams']] == ['Chelsea', 'Manchester United']
        token = data['session_token']
        answer = ask(client, token, "Track Bruno's headed shots")
        assert answer['snapshot']['match_id'] == 'product-demo-match'
        offer = answer['offers'][0]
        assert any(p['field'] == 'player_id' and p['value'] in ('bruno', ['bruno']) for p in offer['rule']['predicates'])
        client.post(f'/product/{token}/offers/{offer["id"]}/track')
        for _ in range(len(lab.source.events)):
            client.portal.call(lab.advance)
        client.portal.call(app.state.product.refresh)
        view = client.get(f'/product/{token}').json()['snapshot']
        assert view['cards'][-1]['value'] == 3
        assert [t['score'] for t in view['match']['teams']] == [1, 0]
        bruno = next(event for event in view['events'] if event['player_id'] == 'bruno')
        assert bruno['player_name'] == 'Bruno Fernandes'
        assert bruno['team_name'] == 'Manchester United'
        assert all(event.get('player_name') != 'Kylian Mbappé' for event in view['events'])
        assert client.post('/lab/recording/default').status_code == 200
        assert lab.source.fingerprint == original
        assert client.get(f'/product/{token}').status_code == 409


def test_product_recording_seed_only_on_fresh_storage(store):
    from backend.adapters.product_demo import load_product_demo
    from test_lab_api import make_lab
    from backend.app import create_app
    lab = make_lab(store)
    lab.initial_recording = (load_product_demo(), 'product-demo.json')
    with TestClient(create_app(store, lab=lab)) as client:
        assert lab.source.match_id == 'product-demo-match'
        client.post('/lab/recording/default')
        client.portal.call(lab.advance)
        retained_run = lab.run_id
    restarted = make_lab(store)
    restarted.initial_recording = (load_product_demo(), 'product-demo.json')
    with TestClient(create_app(store, lab=restarted)):
        assert restarted.source.match_id == 'filter-lab-match'
        assert restarted.run_id == retained_run
        assert restarted.position == 1


def test_invalid_socket_session_has_terminal_close_code(store):
    _, _, _, app = product(store)
    with TestClient(app) as client:
        with client.websocket_connect(f'/product/{uuid4()}/live') as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4001


def test_bootstrap_upstream_failure_is_retryable(store):
    _, questions, _, app = product(store)
    async def unavailable(*args, **kwargs):
        raise RuntimeError('upstream unavailable')
    questions.match_data.stats = unavailable
    with TestClient(app) as client:
        failed = client.post('/product/sessions', json={'profile_id':'chelsea-analytical'})
        assert failed.status_code == 503
        assert failed.json()['code'] == 'snapshot_unavailable'


def test_unpin_revision_fences_older_queued_snapshots(store):
    _, _, _, app = product(store)
    with TestClient(app) as client:
        token = start(client)['session_token']
        offer = ask(client, token, "Track Mbappe's headed shots")['offers'][0]
        tracked = client.post(f'/product/{token}/offers/{offer["id"]}/track').json()
        calculation_id = tracked['calculation']['id']
        # A paused transport may still hold this earlier frame after HTTP unpin.
        before = client.get(f'/product/{token}').json()['snapshot']
        removed = client.delete(f'/product/{token}/pins/{calculation_id}').json()['snapshot']
        assert removed['version'] > before['version']
        assert any(card['kind'] == 'custom' for card in before['cards'])
        assert all(card['kind'] == 'standard' for card in removed['cards'])
        latest = client.get(f'/product/{token}').json()['snapshot']
        assert latest['version'] == removed['version']
        client.portal.call(app.state.product.refresh)
        assert client.get(f'/product/{token}').json()['snapshot']['version'] > removed['version']


def test_process_restart_changes_projection_epoch_not_match_run(store):
    lab, _, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
        token = data['session_token']
        for _ in range(4):
            client.portal.call(lab.advance)
        client.portal.call(app.state.product.refresh)
        before = client.get(f'/product/{token}').json()['snapshot']
    _, _, _, restarted = product(store)
    with TestClient(restarted) as client:
        after = client.get(f'/product/{token}').json()['snapshot']
        assert after['match']['run_id'] == before['match']['run_id']
        assert after['match']['position'] == before['match']['position']
        assert after['projection_epoch'] != before['projection_epoch']
        assert after['version'] < before['version']


def test_event_labels_are_roster_scoped_and_unknown_ids_do_not_invent_names(store):
    lab, questions, _, app = product(store)
    original = questions.narratives.read
    async def with_unknown(snapshot, operation, **filters):
        result = await original(snapshot, operation, **filters)
        if operation == 'viewer':
            result['events'].append({'event_id': 'unknown', 'match_id': snapshot.match_id,
                'team_id': 'not-in-roster', 'player_id': 'not-in-roster'})
        return result
    questions.narratives.read = with_unknown
    with TestClient(app) as client:
        token = start(client)['session_token']
        client.portal.call(lab.advance)
        client.portal.call(app.state.product.refresh)
        events = client.get(f'/product/{token}').json()['snapshot']['events']
        assert events[0]['player_name'] == 'Kylian Mbappé'
        assert events[0]['team_name'] == 'Madrid'
        assert events[-1]['player_name'] is None
        assert events[-1]['team_name'] is None


def test_standard_offer_pins_upstream_value_and_streams_without_custom_engine(store):
    lab, questions, _, app = product(store)
    original = questions.match_data.stats

    async def supplied_values(snapshot):
        result = await original(snapshot)
        for stat in result['stats']:
            if stat['id'] == 'all:shots':
                stat['value'] = 1000 + snapshot.cursor
        return result

    async def forbidden(*args, **kwargs):
        raise AssertionError('An ETL pin must not compile a rule or search event history')

    questions.match_data.stats = supplied_values
    questions.match_data.events = questions.planner.plan = forbidden
    with TestClient(app) as client:
        token = start(client)['session_token']
        offer = ask(client, token, 'how many Both teams shots')['offers'][0]
        assert offer['kind'] == 'standard' and offer['value'] == 1000
        assert 'rule' not in offer
        client.portal.call(lab.advance)
        response = client.post(f'/product/{token}/offers/{offer["id"]}/track')
        assert response.status_code == 200, response.text
        tracked = response.json()
        identifier = tracked['calculation']['id']
        assert identifier == 'standard:all:shots'
        assert tracked['calculation']['value'] == 1001
        card = tracked['snapshot']['cards'][-1]
        assert card['id'] == 'all:shots' and card['value'] == 1001
        assert card['pinned'] and card['pin_id'] == identifier
        assert len(tracked['snapshot']['cards']) == 5
        assert lab.engine.count == 0
        with client.websocket_connect(f'/product/{token}/live') as ws:
            assert ws.receive_json()['cards'][-1]['value'] == 1001
            client.portal.call(lab.advance)
            assert ws.receive_json()['cards'][-1]['value'] == 1002
        other = start(client, 'neutral-simple')
        assert not any(c.get('pinned') for c in other['snapshot']['cards'])
        assert client.post(f'/product/{other["session_token"]}/offers/{offer["id"]}/track').status_code == 404
    # Pins survive API restart without recreating a custom accumulator.
    _, _, _, restarted = product(store)
    with TestClient(restarted) as client:
        restored = start(client)
        assert restored['snapshot']['cards'][-1]['pin_id'] == identifier
        assert len(restored['snapshot']['cards']) == 5
        removed = client.delete(f'/product/{restored["session_token"]}/pins/{identifier}').json()['snapshot']
        assert not any(c.get('pinned') for c in removed['cards'])
        assert [c['id'] for c in removed['cards']] == [
            'chelsea:goals', 'chelsea:shots', 'chelsea:corners', 'chelsea:passes', 'chelsea:cards']


def test_pin_existing_bucket_stat_deduplicates_and_unpin_restores_rank(store):
    _, _, _, app = product(store)
    with TestClient(app) as client:
        token = start(client, 'neutral-simple')['session_token']
        initial = client.get(f'/product/{token}').json()['snapshot']['cards']
        for _ in range(2):
            offer = ask(client, token, 'how many Both teams shots')['offers'][0]
            response = client.post(f'/product/{token}/offers/{offer["id"]}/track')
            assert response.status_code == 200, response.text
            cards = response.json()['snapshot']['cards']
            assert len(cards) == 5
            assert len({c['id'] for c in cards}) == 5
            assert sum(c.get('pinned', False) for c in cards) == 1
            assert {c['id'] for c in cards} == {c['id'] for c in initial}
        removed = client.delete(f'/product/{token}/pins/standard:all:shots').json()['snapshot']['cards']
        assert removed == initial
        assert all(o['calculation_id'] is None for o in client.get(f'/product/{token}').json()['offers'])


def test_clarification_reply_resolves_to_pinnable_custom_stat(store):
    from backend.models.questions import QuestionDraft

    class Clarifying:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            if prompt == 'How many headers by Mbappe?':
                return QuestionDraft(answer_kind='statistic', status='clarification',
                                     text='Headed passes, headed shots or all recorded contacts?')
            assert prompt == 'Headed shots'
            assert context['history'][-1]['user'] == 'How many headers by Mbappe?'
            assert context['history'][-1]['reply']['status'] == 'clarification'
            prepared = await tools.prepare("Track Mbappe's headed shots")
            return QuestionDraft(answer_kind='statistic', status='answer', text='Prepared.',
                                 selected_offer_id=prepared['offer_id'])

    lab, questions, _, app = product(store)
    questions.agent = Clarifying()
    with TestClient(app) as client:
        token = start(client)['session_token']
        first = ask(client, token, 'How many headers by Mbappe?')
        assert first['status'] == 'clarification' and first['offers'] == []
        second = ask(client, token, 'Headed shots')
        assert second['status'] == 'answer' and len(second['offers']) == 1
        offer = second['offers'][0]
        assert lab.engine.count == 0
        tracked = client.post(f'/product/{token}/offers/{offer["id"]}/track').json()
        assert tracked['snapshot']['cards'][-1]['pinned']
        for _ in range(len(lab.source.events)):
            client.portal.call(lab.advance)
        client.portal.call(app.state.product.refresh)
        assert client.get(f'/product/{token}').json()['snapshot']['cards'][-1]['value'] == 3


def test_unavailable_standard_stat_cannot_be_pinned(store):
    lab, questions, _, app = product(store)
    original = questions.match_data.stats

    async def unavailable(snapshot):
        result = await original(snapshot)
        for stat in result['stats']:
            if stat['id'] == 'all:shots':
                stat['available'] = False
        return result

    with TestClient(app) as client:
        token = start(client)['session_token']
        offer = ask(client, token, 'how many Both teams shots')['offers'][0]
        questions.match_data.stats = unavailable
        response = client.post(f'/product/{token}/offers/{offer["id"]}/track')
        assert response.status_code == 503 and response.json()['code'] == 'stat_unavailable'
        assert lab.engine.count == 0
        assert client.get(f'/product/{token}').json()['offers'][0]['calculation_id'] is None
