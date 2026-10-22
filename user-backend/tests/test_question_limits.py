"""Admission and cheap session identity checks, independent of model behaviour."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event as ThreadEvent

import pytest

from backend.domain import RuleError
from backend.services.questions import QuestionService
from benchmarks.doubles.question_agent import FixtureQuestionAgent
from harness import MATCH, Running, ask, session

CHAT = f'/lab/matches/{MATCH}/chat'


def counting(run):
    captured = []
    original = run.service.match_data.capture

    async def capture(match, seq=None):
        result = await original(match, seq)
        captured.append(result.snapshot.id)
        return result
    run.service.match_data.capture = capture
    return captured


def test_session_start_and_poll_do_not_capture_history_and_question_captures_once(store):
    with Running(store) as run:
        captured = counting(run)
        run.send(12)
        token = session(run.client)
        for _ in range(3):
            assert run.client.get(f'{CHAT}/{token}').status_code == 200
        assert captured == []
        response = ask(run.client, token, 'what is offside')
        assert response.status_code == 200 and response.json()['status'] == 'answer'
        assert captured == [f'{MATCH}:12']
        run.client.post('/admin/matches/purge', json={'match_id': MATCH})
        assert run.client.get(f'{CHAT}/{token}').status_code == 404
        assert len(captured) == 1


def test_takeover_and_other_profiles_cannot_bypass_shared_admission(store):
    entered, release = ThreadEvent(), ThreadEvent()

    class Waiting(FixtureQuestionAgent):
        async def answer(self, prompt, context, tools):
            entered.set()
            await asyncio.to_thread(release.wait, 4)
            return await super().answer(prompt, context, tools)
    with Running(store, agent=Waiting(), max_active=1) as run, ThreadPoolExecutor() as pool:
        captured = counting(run)
        old = session(run.client)
        pending = pool.submit(ask, run.client, old, 'what is offside')
        try:
            assert entered.wait(3)
            replacement = session(run.client)
            other_profile = session(run.client, profile='united-casual')
            for token in [replacement, other_profile]:
                refused = ask(run.client, token, 'what is offside')
                assert refused.status_code == 503 and refused.json()['code'] == 'question_capacity'
                assert all(turn['status'] != 'pending' for turn in run.client.get(f'{CHAT}/{token}').json()['turns'])
            assert len(captured) == 1, 'Rejected work must not build a snapshot'
        finally:
            release.set()
        assert pending.result(timeout=5).status_code == 409
        response = ask(run.client, replacement, 'what is offside')
        assert response.status_code == 200 and response.json()['status'] == 'answer'
        assert len(captured) == 2


def test_admission_releases_on_cancellation_and_exception_without_queueing():
    async def run():
        service = QuestionService(None, None, None, None, object(), None, None, max_active=1)
        entered = asyncio.Event()

        async def blocked(*args):
            entered.set()
            await asyncio.Event().wait()
        service._ask = blocked
        first = asyncio.create_task(service.ask('match', 'token', 'id', 'question'))
        await entered.wait()
        with pytest.raises(RuleError) as error:
            await service.ask('match', 'other-token', 'other-id', 'question')
        assert error.value.code == 'question_capacity'
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        async def broken(*args):
            raise RuntimeError('test failure')
        service._ask = broken
        with pytest.raises(RuntimeError):
            await service.ask('match', 'token', 'id', 'question')

        async def ready(*args):
            return 'ready'
        service._ask = ready
        assert await service.ask('match', 'token', 'id', 'question') == 'ready'
    asyncio.run(run())


def test_purge_between_register_and_offer_link_cannot_report_tracking_success(store):
    registered, release = ThreadEvent(), ThreadEvent()
    with Running(store) as run, ThreadPoolExecutor() as pool:
        match = run.match()
        original = match.register

        async def pause_after_registration(*args):
            result = await original(*args)
            registered.set()
            await asyncio.to_thread(release.wait, 4)
            return result
        match.register = pause_after_registration
        token = session(run.client)
        response = ask(run.client, token, "Track Mbappe's headed shots")
        assert response.json()['status'] == 'answer', response.text
        offer_id = response.json()['offers'][0]['id']
        tracking = pool.submit(run.client.post, f'{CHAT}/{token}/offers/{offer_id}/track')
        try:
            assert registered.wait(3)
            assert run.client.post('/admin/matches/purge', json={'match_id': MATCH}).status_code == 200
        finally:
            release.set()
        failed = tracking.result(timeout=5)
        assert failed.status_code == 404 and failed.json()['code'] == 'match_not_found'
        assert run.client.get(f'/lab/matches/{MATCH}/state').status_code == 404


@pytest.mark.parametrize('limit', [0, 33, -1, True, 1.5])
def test_invalid_active_question_limit_fails_early(limit):
    with pytest.raises(ValueError, match='QUESTION_MAX_ACTIVE'):
        QuestionService(None, None, None, None, None, None, None, max_active=limit)


def test_session_locks_are_per_match_and_unused_locks_drop_out(store):
    import gc
    from backend.services.locks import KeyedLocks
    from test_product import OTHER
    with Running(store, matches=(MATCH, OTHER)) as run:
        product, questions = run.app.state.product, run.app.state.questions

        async def check():
            async with product._locks(MATCH), questions.session_guard(MATCH):
                # Another match's sessions never wait for this one.
                other = await asyncio.wait_for(product.start(OTHER, 'riverton-analytical'), 5)
                blocked = asyncio.create_task(product.start(MATCH, 'riverton-analytical'))
                await asyncio.sleep(0.2)
                assert other['match_id'] == OTHER and not blocked.done()
            return await asyncio.wait_for(blocked, 5)
        assert run.client.portal.call(check)['match_id'] == MATCH
    locks = KeyedLocks()
    lock = locks('a')
    assert locks('a') is lock and locks('b') is not lock
    del lock
    gc.collect()
    assert len(locks._locks) == 0
