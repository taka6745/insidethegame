"""Viewer choices persist; connected viewers alone activate generation targets."""
from itertools import product as combinations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from test_product import product, start, ask


def select(client, token, team='away', style='experienced'):
    response = client.put(f'/product/{token}/audience', json={'team': team, 'fan_style': style})
    assert response.status_code == 200, response.text
    return response.json()


def catalogue(client, match_id):
    response = client.get(f'/matches/{match_id}/audience-config')
    assert response.status_code == 200, response.text
    return response


def enabled(client, match_id):
    body = catalogue(client, match_id).json()
    assert len(body['buckets']) == 12
    assert {b['id'] for b in body['buckets'] if b['enabled']} == {
        t['bucket_id'] for t in body['generation_targets']}
    return {t['bucket_id'] for t in body['generation_targets']}


def test_all_audiences_reroute_backlog_and_stats_without_changing_account(store):
    lab, questions, _, app = product(store)
    with TestClient(app) as client:
        client.post('/product/demo/reset')
        data = start(client)
        token, match_id = data['session_token'], data['match_id']
        profiles = questions.repository.profiles()
        for _ in lab.source.events:
            client.portal.call(lab.advance)
        client.portal.call(app.state.product.refresh)
        version = 0
        with client.websocket_connect(f'/product/{token}/live') as ws:
            ws.receive_json()
            for team, style in combinations(('home', 'away', 'neutral'), ('simple', 'casual', 'analytical', 'experienced')):
                updated = select(client, token, team, style)
                snapshot = updated['snapshot']
                assert snapshot['audience'] == updated['audience'] == {'team': team, 'fan_style': style}
                support = {'home': 'chelsea', 'away': 'manutd', 'neutral': 'neutral'}[team]
                assert snapshot['bucket'] == f'{support}:{style}'
                assert snapshot['version'] > version
                version = snapshot['version']
                assert snapshot['narratives'] and all(snapshot['bucket'] in n['buckets'] for n in snapshot['narratives'])
                assert len(snapshot['cards']) == 5
                assert all(card['id'].startswith(('all' if team == 'neutral' else support) + ':') for card in snapshot['cards'])
                assert ws.receive_json()['audience'] == snapshot['audience']
                assert enabled(client, match_id) == {f'{team}:{style}'}
        assert questions.repository.profiles() == profiles


def test_choice_preserves_chat_pins_and_survives_takeover_refresh_and_restart(store):
    _, _, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
        token = data['session_token']
        offer = ask(client, token, 'how many Both teams shots')['offers'][0]
        assert client.post(f'/product/{token}/offers/{offer["id"]}/track').status_code == 200
        before = client.get(f'/product/{token}').json()
        selected = select(client, token)
        assert selected['turns'] == before['turns'] and selected['offers'] == before['offers']
        assert selected['snapshot']['cards'][-1]['pin_id'] == 'standard:all:shots'
        assert client.get(f'/product/{token}').json()['audience'] == selected['audience']
        takeover = start(client)
        assert takeover['audience'] == selected['audience']
        assert takeover['turns'] == before['turns']
        assert client.get(f'/product/{token}').status_code == 409
        token = takeover['session_token']
        assert start(client, 'neutral-simple')['audience'] == {'team': 'neutral', 'fan_style': 'simple'}
    _, _, _, restarted = product(store)
    with TestClient(restarted) as client:
        restored = client.get(f'/product/{token}').json()
        assert restored['audience'] == selected['audience']
        assert restored['snapshot']['cards'][-1]['pinned']
        assert enabled(client, restored['match_id']) == set()


@pytest.mark.parametrize('body', [
    {'team': 'chelsea', 'fan_style': 'simple'}, {'team': 'home', 'fan_style': 'expert'},
    {'team': 'home'}, {'team': 'home', 'fan_style': 'simple', 'enabled': True}])
def test_invalid_choices_never_write(store, body):
    _, _, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
        token = data['session_token']
        before = catalogue(client, data['match_id']).json()
        assert client.put(f'/product/{token}/audience', json=body).status_code == 422
        assert client.get(f'/product/{token}').json()['audience'] == data['audience']
        assert catalogue(client, data['match_id']).json() == before


def test_connected_union_deduplicates_and_removes_only_departing_audience(store):
    lab, _, _, app = product(store)
    with TestClient(app) as client:
        a = start(client)
        b = start(client, 'neutral-simple')
        path = f'/matches/{a["match_id"]}/audience-config'
        assert enabled(client, a['match_id']) == set()
        with client.websocket_connect(f'/product/{a["session_token"]}/live') as first:
            first.receive_json()
            assert enabled(client, a['match_id']) == {'home:analytical'}
            with client.websocket_connect(f'/product/{b["session_token"]}/live') as second:
                second.receive_json()
                assert enabled(client, a['match_id']) == {'home:analytical', 'neutral:simple'}
                tag = catalogue(client, a['match_id']).headers['etag']
                # Match events and session polling must not rewrite presence/revision.
                client.portal.call(lab.advance)
                first.receive_json(); second.receive_json()
                client.get(f'/product/{a["session_token"]}')
                assert client.get(path, headers={'If-None-Match': tag}).status_code == 304
                select(client, b['session_token'], 'home', 'analytical')
                assert enabled(client, a['match_id']) == {'home:analytical'}
            # One of two viewers of the same combination left: it remains enabled.
            assert enabled(client, a['match_id']) == {'home:analytical'}
        assert enabled(client, a['match_id']) == set()


def test_takeover_and_same_token_socket_replacement_keep_correct_presence(store):
    _, _, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
        token = data['session_token']
        with client.websocket_connect(f'/product/{token}/live') as first:
            first.receive_json()
            with client.websocket_connect(f'/product/{token}/live') as replacement:
                replacement.receive_json()
                with pytest.raises(WebSocketDisconnect):
                    first.receive_json()
                assert enabled(client, data['match_id']) == {'home:analytical'}
                # Lab takeover shares identity but is not a viewer subscription.
                client.post('/lab/chat/sessions', json={'profile_id': data['profile_id']})
                with pytest.raises(WebSocketDisconnect):
                    replacement.receive_json()
                assert enabled(client, data['match_id']) == set()


def test_reset_and_recording_switch_clear_old_flags_and_reset_match_choices(store):
    _, _, _, app = product(store)
    with TestClient(app) as client:
        first = start(client)
        token = first['session_token']
        select(client, token)
        with client.websocket_connect(f'/product/{token}/live') as ws:
            ws.receive_json()
            assert enabled(client, first['match_id']) == {'away:experienced'}
            assert client.post('/product/demo/reset').status_code == 200
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert enabled(client, first['match_id']) == set()
        second = start(client)
        assert second['match_id'] == 'product-demo-match'
        assert second['audience'] == {'team': 'home', 'fan_style': 'analytical'}
        assert enabled(client, second['match_id']) == set()


def test_restart_clears_abandoned_db_flags(store):
    _, _, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
    # Simulate a crash leaving presence flags committed but no connected clients.
    app.state.product.audiences.repository.set_viewer_targets(data['match_id'], {('away', 'casual')})
    _, _, _, restarted = product(store)
    with TestClient(restarted) as client:
        assert enabled(client, data['match_id']) == set()


def test_canonical_generation_target_ids_route_text_and_stat_recommendations(store):
    _, questions, _, app = product(store)
    original = questions.narratives.read

    async def canonical(snapshot, operation, **filters):
        result = await original(snapshot, operation, **filters)
        if operation == 'viewer':
            result['items'] = [
                {'id': team, 'text': f'{team} supplied text.', 'buckets': [f'{team}:analytical'],
                 'stat_ids': ['all:cards', 'all:shots'], 'clock_seconds': 0}
                for team in ('home', 'away', 'neutral')]
        return result

    questions.narratives.read = canonical
    with TestClient(app) as client:
        token = start(client)['session_token']
        for team in ('home', 'away', 'neutral'):
            data = select(client, token, team, 'analytical')
            view = data['snapshot']
            target = next(b for b in catalogue(client, data['match_id']).json()['buckets']
                          if b['selections'] == data['audience'])
            assert view['bucket_id'] == target['id']
            assert [n['text'] for n in view['narratives']] == [f'{team} supplied text.']
            assert [c['id'] for c in view['cards']] == ['all:cards', 'all:shots']


def test_transient_presence_failure_keeps_saved_choice_and_retries(store, monkeypatch):
    _, _, _, app = product(store)
    with TestClient(app) as client:
        data = start(client)
        token = data['session_token']
        presence = app.state.product.presence
        original = presence.repository.set_viewer_targets
        attempts = []

        def fail_once(match_id, choices):
            attempts.append(choices)
            if len(attempts) == 1:
                raise RuntimeError('Temporary presence write failure')
            return original(match_id, choices)

        with client.websocket_connect(f'/product/{token}/live') as ws:
            ws.receive_json()
            monkeypatch.setattr(presence.repository, 'set_viewer_targets', fail_once)
            updated = select(client, token)
            assert updated['audience'] == {'team': 'away', 'fan_style': 'experienced'}
            assert ws.receive_json()['audience'] == updated['audience']
            client.portal.call(app.state.product.refresh)
            assert client.get(f'/product/{token}').json()['audience'] == updated['audience']
            assert enabled(client, data['match_id']) == {'away:experienced'}
            assert len(attempts) >= 2


def test_question_agent_uses_match_audience_override(store):
    from backend.models.questions import QuestionDraft

    class InspectProfile:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            assert context['profile']['team'] == 'away'
            assert context['profile']['fan_style'] == 'experienced'
            assert set(context['profile']) == {'team', 'fan_style'}
            return QuestionDraft(status='answer', answer_kind='football', text='A corner restarts play.')

    _, questions, _, app = product(store)
    questions.agent = InspectProfile()
    with TestClient(app) as client:
        token = start(client)['session_token']
        select(client, token)
        assert ask(client, token, 'What is a corner?')['status'] == 'answer'


def test_reset_between_selection_validation_and_commit_rejects_old_run(store):
    import asyncio
    from backend.domain import RuleError
    from backend.models.viewer_audience import ViewerAudience

    lab, questions, _, app = product(store)
    with TestClient(app) as client:
        token = start(client)['session_token']
        service = app.state.product
        original = service.audiences.read

        async def interleave():
            read, release = asyncio.Event(), asyncio.Event()

            async def pause(match_id):
                result = await original(match_id)
                read.set()
                await release.wait()
                return result

            service.audiences.read = pause
            changing = asyncio.create_task(service.select_audience(token, ViewerAudience(team='away', fan_style='casual')))
            await read.wait()
            await lab.reset()
            release.set()
            with pytest.raises(RuleError) as error:
                await changing
            assert error.value.code == 'run_changed'

        client.portal.call(interleave)
        assert questions.repository.read(token)['audience'] is None


def test_background_projection_failure_cannot_interrupt_committed_choice(store):
    import asyncio
    from backend.models.viewer_audience import ViewerAudience

    _, _, _, app = product(store)
    with TestClient(app) as client:
        token = start(client)['session_token']
        service = app.state.product
        original_sync = service.presence.sync

        async def interleave():
            committing, release = asyncio.Event(), asyncio.Event()

            async def pause():
                committing.set()
                await release.wait()
                await original_sync()

            async def unavailable():
                raise RuntimeError('Temporary upstream failure')

            service.presence.sync = pause
            changing = asyncio.create_task(service.select_audience(token, ViewerAudience(team='away', fan_style='casual')))
            await committing.wait()
            service.refresh = unavailable
            service.lab.changed.set()
            await asyncio.sleep(0)
            assert service.shared is not None  # failure waits for the committing selection
            release.set()
            result = await changing
            assert result['snapshot']['audience'] == {'team': 'away', 'fan_style': 'casual'}
            return result

        result = client.portal.call(interleave)
        assert result['audience'] == {'team': 'away', 'fan_style': 'casual'}


def test_disconnect_during_narrative_fetch_refreshes_same_match_cursor(store):
    """An in-flight response cannot consume a newer audience invalidation."""
    import asyncio
    from contextlib import suppress

    lab, questions, _, app = product(store)
    questions.narratives.audience_dependent = True
    original = questions.narratives.read
    with TestClient(app) as client:
        token = start(client)['session_token']
        service = app.state.product

        async def interleave():
            # Drive refreshes explicitly so the barrier fixes the exact ordering.
            service._task.cancel()
            with suppress(asyncio.CancelledError):
                await service._task
            peer, _ = await service.attach(token)
            await service.refresh()
            fetched, release = asyncio.Event(), asyncio.Event()
            reads = []

            async def pause(snapshot, operation, **filters):
                result = await original(snapshot, operation, **filters)
                catalogue, _ = await service.audiences.read(snapshot.match_id)
                targets = [target['bucket_id'] for target in catalogue['generation_targets']]
                reads.append(targets)
                result['items'] = [{'id': target, 'text': 'Observed match commentary.',
                                    'buckets': [target], 'stat_ids': [], 'clock_seconds': 0}
                                   for target in targets]
                if len(reads) == 1:
                    fetched.set()
                    await release.wait()
                return result

            questions.narratives.read = pause
            await lab.advance()
            refreshing = asyncio.create_task(service.refresh())
            await asyncio.wait_for(fetched.wait(), 5)
            await service.detach(peer)
            release.set()
            await asyncio.wait_for(refreshing, 5)
            cursor = service.shared['match']['position']
            assert service.shared['narratives']
            await service.refresh()
            assert service.shared['match']['position'] == cursor
            assert service.shared['narratives'] == []
            assert reads == [['home:analytical'], []]

        client.portal.call(interleave)


def test_saved_audience_retry_commits_targets_before_narrative_read(store, monkeypatch):
    import asyncio
    from contextlib import suppress
    from backend.models.viewer_audience import ViewerAudience

    _, questions, _, app = product(store)
    questions.narratives.audience_dependent = True
    original_read = questions.narratives.read
    with TestClient(app) as client:
        token = start(client)['session_token']
        service = app.state.product

        async def retry():
            service._task.cancel()
            with suppress(asyncio.CancelledError):
                await service._task
            await service.attach(token)
            await service.refresh()
            original_write = service.presence.repository.set_viewer_targets
            attempts, reads = [], []

            def fail_once(match_id, choices):
                attempts.append(choices)
                if len(attempts) == 1:
                    raise RuntimeError('Temporary presence write failure')
                return original_write(match_id, choices)

            async def read_targets(snapshot, operation, **filters):
                result = await original_read(snapshot, operation, **filters)
                catalogue, _ = await service.audiences.read(snapshot.match_id)
                reads.append([target['bucket_id'] for target in catalogue['generation_targets']])
                return result

            monkeypatch.setattr(service.presence.repository, 'set_viewer_targets', fail_once)
            questions.narratives.read = read_targets
            chosen = ViewerAudience(team='away', fan_style='experienced')
            result = await service.select_audience(token, chosen)
            assert result['audience'] == chosen.model_dump()
            await service.refresh()
            assert len(attempts) == 2
            assert reads == [['away:experienced']]

        client.portal.call(retry)
