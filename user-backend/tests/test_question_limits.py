"""Admission and cheap session identity checks, independent of model behaviour."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event as ThreadEvent

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.question_data import GraphQLQuestionData
from backend.agents.question_fixture import FixtureQuestionAgent
from backend.app import create_app
from backend.domain import RuleError
from backend.fakes import create_fake
from backend.repositories.questions import QuestionRepository
from backend.services.question_snapshot import LabSnapshotProvider
from backend.services.questions import QuestionService
from test_lab_api import make_lab
from test_questions import session, ask


def build(store, agent=None, max_active=1):
    lab = make_lab(store)
    upstreams = [create_fake('etl'), create_fake('narrative')]
    adapters = [GraphQLQuestionData('http://fake/graphql', bridge=True, transport=httpx.ASGITransport(app=app))
                for app in upstreams]
    snapshots = LabSnapshotProvider(lab)
    service = QuestionService(QuestionRepository(store), snapshots, *adapters,
                              agent or FixtureQuestionAgent(), lab.planner, timeout=5, max_active=max_active)
    return lab, service, create_app(store, lab=lab, questions=service)


def test_session_start_and_poll_do_not_capture_history_and_question_captures_once(store):
    lab, service, app = build(store)
    captured = []
    original = service.snapshots.capture
    async def capture():
        result = await original()
        captured.append(result.snapshot.id)
        return result
    service.snapshots.capture = capture
    with TestClient(app) as client:
        for _ in range(12):
            client.portal.call(lab.advance)
        token = session(client)
        for _ in range(3):
            assert client.get(f'/lab/chat/{token}').status_code == 200
        assert captured == []
        response = ask(client, token, 'what is offside')
        assert response.status_code == 200 and response.json()['status'] == 'answer'
        assert len(captured) == 1
        client.post('/lab/reset')
        assert client.get(f'/lab/chat/{token}').status_code == 409
        assert len(captured) == 1


def test_takeover_and_other_profiles_cannot_bypass_shared_admission(store):
    entered, release = ThreadEvent(), ThreadEvent()
    class Waiting(FixtureQuestionAgent):
        async def answer(self, prompt, context, tools):
            entered.set()
            await asyncio.to_thread(release.wait, 4)
            return await super().answer(prompt, context, tools)
    _, service, app = build(store, Waiting())
    captured = []
    original = service.snapshots.capture
    async def capture():
        captured.append(True)
        return await original()
    service.snapshots.capture = capture
    with TestClient(app) as client, ThreadPoolExecutor() as pool:
        old = session(client)
        pending = pool.submit(ask, client, old, 'what is offside')
        try:
            assert entered.wait(3)
            replacement = session(client)
            other_profile = session(client, 'united-casual')
            for token in [replacement, other_profile]:
                refused = ask(client, token, 'what is offside')
                assert refused.status_code == 503
                assert refused.json()['code'] == 'question_capacity'
                assert all(turn['status'] != 'pending' for turn in client.get(f'/lab/chat/{token}').json()['turns'])
            assert len(captured) == 1, 'Rejected work must not build a snapshot'
        finally:
            release.set()
        assert pending.result(timeout=5).status_code == 409
        response = ask(client, replacement, 'what is offside')
        assert response.status_code == 200 and response.json()['status'] == 'answer'
        assert len(captured) == 2


def test_admission_releases_on_cancellation_and_exception_without_queueing():
    async def run():
        service = QuestionService(None, None, None, None, None, None, max_active=1)
        entered = asyncio.Event()
        async def blocked(*args):
            entered.set()
            await asyncio.Event().wait()
        service._ask = blocked
        first = asyncio.create_task(service.ask('token', 'id', 'question'))
        await entered.wait()
        with pytest.raises(RuleError) as error:
            await service.ask('other-token', 'other-id', 'question')
        assert error.value.code == 'question_capacity'
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        async def broken(*args):
            raise RuntimeError('test failure')
        service._ask = broken
        with pytest.raises(RuntimeError):
            await service.ask('token', 'id', 'question')
        async def ready(*args):
            return 'ready'
        service._ask = ready
        assert await service.ask('token', 'id', 'question') == 'ready'
    asyncio.run(run())


def test_reset_between_register_and_offer_link_cannot_report_tracking_success(store):
    registered, release = ThreadEvent(), ThreadEvent()
    _, service, app = build(store)
    original = service.snapshots.track
    async def pause_after_registration(*args):
        result = await original(*args)
        registered.set()
        await asyncio.to_thread(release.wait, 4)
        return result
    service.snapshots.track = pause_after_registration
    with TestClient(app) as client, ThreadPoolExecutor() as pool:
        token = session(client)
        response = ask(client, token, "Track Mbappe's headed shots")
        assert response.json()['status'] == 'answer', response.text
        offer_id = response.json()['offers'][0]['id']
        tracking = pool.submit(client.post, f'/lab/chat/{token}/offers/{offer_id}/track')
        try:
            assert registered.wait(3)
            assert client.post('/lab/reset').status_code == 200
        finally:
            release.set()
        failed = tracking.result(timeout=5)
        assert failed.status_code == 409 and failed.json()['code'] == 'run_changed'
        assert service.repository.offer(token, offer_id)['calculation_id'] is None
        assert client.get('/lab/state').json()['calculations'] == []


@pytest.mark.parametrize('limit', [0, 33, -1, True, 1.5])
def test_invalid_active_question_limit_fails_early(limit):
    with pytest.raises(ValueError, match='QUESTION_MAX_ACTIVE'):
        QuestionService(None, None, None, None, None, None, max_active=limit)


def test_errored_run_blocks_questions_but_not_startup_identity(store):
    lab = make_lab(store)
    lab.status = 'error'
    snapshots = LabSnapshotProvider(lab)
    with pytest.raises(RuleError):
        asyncio.run(snapshots.identity())
    assert asyncio.run(snapshots.identity(allow_error=True)).run_id == str(lab.run_id)


def test_question_pins_to_newest_observed_narrative_cursor_never_later(store):
    lab, service, app = build(store)
    with TestClient(app) as client:
        for _ in range(12):
            client.portal.call(lab.advance)
        async def observed(snapshot):
            return 5
        service.narratives.observed_cursor = observed
        assert client.portal.call(service._capture).snapshot.cursor == 5
        async def ahead(snapshot):
            return snapshot.cursor + 3
        service.narratives.observed_cursor = ahead
        assert client.portal.call(service._capture).snapshot.cursor == lab.position
