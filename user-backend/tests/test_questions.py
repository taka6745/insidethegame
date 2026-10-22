"""Question integration: real Postgres, stream-fed matches and ETL GraphQL doubles."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event as ThreadEvent
from uuid import uuid4

import httpx
import pytest

from backend.models.questions import QuestionDraft
from benchmarks.doubles.recording import FixtureEventSource
from harness import MATCH, Running, Upstream, ask, session


def test_standard_stats_are_upstream_and_no_custom_rule_or_history(store):
    with Running(store) as run:
        async def forbidden(*args, **kwargs):
            raise AssertionError('Standard stats must not compile rules')
        run.service.planner.plan = forbidden
        run.send(15)
        token = session(run.client)
        reply = ask(run.client, token, 'how many Both teams shots').json()
        assert reply['status'] == 'answer', reply
        assert reply['snapshot']['id'] == f'{MATCH}:15' and reply['snapshot']['seq'] == 15
        # Every reply carries its usage; fixture answers make no model calls.
        assert reply['usage']['calls'] == 0 and reply['usage']['seconds'] >= 0
        assert reply['evidence'][0]['id'] == 'stat:all:shots'
        assert reply['offers'][0]['kind'] == 'standard' and reply['offers'][0]['standard_stat_id'] == 'all:shots'
        assert reply['offers'][0]['match_id'] == MATCH and 'rule' not in reply['offers'][0]
        assert run.match().engine.count == 0


def test_snapshot_never_passes_etl_watermark_or_received_events(store):
    with Running(store) as run:
        run.send(10)
        run.send(5, commit=False)  # Received here, not yet committed by ETL.
        reply = ask(run.client, session(run.client), 'how many Both teams shots').json()
        assert reply['snapshot']['seq'] == 10


def test_one_off_offer_track_catches_up_and_shared_rule_reuse(store):
    with Running(store) as run:
        run.send(10)
        token = session(run.client)
        reply = ask(run.client, token, "Track Mbappe's headed shots").json()
        assert reply['status'] == 'answer', reply
        offer = reply['offers'][0]
        assert offer['value'] == 1 and run.match().engine.count == 0
        run.send(12)
        path = f'/lab/matches/{MATCH}/chat'
        tracked = run.client.post(f'{path}/{token}/offers/{offer["id"]}/track').json()
        assert tracked['calculation']['value'] == 2  # duplicates and a corrected shot count once
        assert run.client.post(f'{path}/{token}/offers/{offer["id"]}/track').json()['calculation'] == tracked['calculation']
        assert run.match().engine.count == 1
        other = session(run.client, profile='united-casual')
        assert run.client.post(f'{path}/{other}/offers/{offer["id"]}/track').status_code == 404
        assert run.client.get(f'{path}/{token}').json()['offers'][0]['calculation_id'] == tracked['calculation']['id']
        assert run.client.post('/admin/matches/purge', json={'match_id': MATCH}).status_code == 200
        assert run.client.post(f'{path}/{token}/offers/{offer["id"]}/track').status_code == 404


def test_retry_takeover_and_restore(store):
    upstream = Upstream()
    with Running(store, upstream=upstream) as run:
        token = session(run.client)
        identifier = str(uuid4())
        first = ask(run.client, token, 'what is offside', identifier)
        assert first.json() == ask(run.client, token, 'what is offside', identifier).json()
        assert ask(run.client, token, 'different', identifier).status_code == 409
        replacement = session(run.client)
        assert run.client.get(f'/lab/matches/{MATCH}/chat/{token}').status_code == 409
        assert len(run.client.get(f'/lab/matches/{MATCH}/chat/{replacement}').json()['turns']) == 1
    with Running(store, upstream=upstream, matches=()) as run:
        restored = run.client.get(f'/lab/matches/{MATCH}/chat/{replacement}')
        assert restored.status_code == 200 and restored.json()['turns'][0]['reply']['status'] == 'answer'


def test_snapshot_does_not_change_while_model_waits_and_duplicate_busy(store):
    entered, release = ThreadEvent(), ThreadEvent()

    class Waiting:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            entered.set()
            await asyncio.to_thread(release.wait, 3)
            result = await tools.standard(['all:shots'])
            return QuestionDraft(answer_kind='match', status='answer', text=str(result['stats'][0]['value']),
                                 evidence_ids=['stat:all:shots'])
    with Running(store, agent=Waiting()) as run, ThreadPoolExecutor() as pool:
        run.send(10)
        token, identifier = session(run.client), str(uuid4())
        pending = pool.submit(ask, run.client, token, 'shots', identifier)
        assert entered.wait(3)
        assert ask(run.client, token, 'shots', identifier).status_code == 409
        assert ask(run.client, token, 'another question').status_code == 409
        run.send(10)
        release.set()
        assert pending.result().json()['snapshot']['seq'] == 10
        assert run.match().seq == 20


@pytest.mark.parametrize('change', ['purge', 'takeover'])
def test_stale_model_callback_cannot_commit(store, change):
    entered, release = ThreadEvent(), ThreadEvent()

    class Waiting:
        mode = 'fixture'

        async def answer(self, *args):
            entered.set()
            await asyncio.to_thread(release.wait, 3)
            return QuestionDraft(answer_kind='match', status='answer', text='A late answer')
    with Running(store, agent=Waiting()) as run, ThreadPoolExecutor() as pool:
        token = session(run.client)
        pending = pool.submit(ask, run.client, token, 'question')
        assert entered.wait(3)
        if change == 'purge':
            run.client.post('/admin/matches/purge', json={'match_id': MATCH})
        else:
            session(run.client)
        release.set()
        assert pending.result().status_code in (404, 409)
        if change == 'takeover':
            new = session(run.client)
            turns = run.client.get(f'/lab/matches/{MATCH}/chat/{new}').json()['turns']
            assert all(t.get('reply', {}).get('text') != 'A late answer' for t in turns)


def test_clarification_and_prior_goal_persist_in_context(store):
    seen = []

    class Clarifying:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            seen.append(context)
            if prompt == 'headers':
                return QuestionDraft(answer_kind='match', status='clarification', text='Headed shots or all recorded contacts?')
            assert context['history'][-1]['reply']['status'] == 'clarification'
            return QuestionDraft(answer_kind='match', status='answer', text='Understood.')
    with Running(store, agent=Clarifying()) as run:
        token = session(run.client)
        assert ask(run.client, token, 'headers').json()['status'] == 'clarification'
        assert ask(run.client, token, 'all contacts').json()['status'] == 'answer'
        assert len(seen[1]['history']) == 1


def test_timeout_does_not_leave_pending(store):
    class Slow:
        mode = 'fixture'

        async def answer(self, *args):
            from backend.adapters.usage import record
            record(b'{"usage":{"prompt_tokens":100,"completion_tokens":5}}')
            await asyncio.sleep(30)
    with Running(store, agent=Slow(), question_timeout=2) as run:
        token = session(run.client)
        response = ask(run.client, token, 'question').json()
        assert response['status'] == 'unsupported' and 'timed out' in response['text']
        assert response['usage']['input_tokens'] == 100 and response['usage']['calls'] == 1
        row = run.client.get(f'/lab/matches/{MATCH}/chat/{token}').json()
        assert row['turns'][0]['status'] == 'failed' and row['turns'][0]['reply']['usage']['output_tokens'] == 5


def test_each_match_is_its_own_identity_with_no_other_match_leak(store):
    data = json.loads(FixtureEventSource().content)
    data['teams'][0]['name'] = 'North Stars'
    mapping = {t['id']: f'team-{i}' for i, t in enumerate(data['teams'])}
    for t in data['teams']:
        t['id'] = mapping[t['id']]
    for p in data['players']:
        p['team_id'] = mapping[p['team_id']]
    for e in data['events']:
        e['teamId'] = mapping.get(e.get('teamId'), e.get('teamId'))
    data['presets'] = []
    upstream = Upstream()
    upstream.add('north-stars-0000aaaa', FixtureEventSource(content=json.dumps(data).encode()))
    upstream.add(MATCH)

    class Inspect:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            assert context['snapshot']['match_id'] == 'north-stars-0000aaaa'
            assert context['teams'][0]['name'] == 'North Stars'
            assert all('riverton' not in json.dumps(s).lower() for s in context['standard_stats'])
            return QuestionDraft(answer_kind='match', status='answer', text='North Stars are playing.')
    with Running(store, agent=Inspect(), upstream=upstream, matches=('north-stars-0000aaaa', MATCH)) as run:
        run.send(5, 'north-stars-0000aaaa')
        run.send(9, MATCH)
        token = session(run.client, 'north-stars-0000aaaa')
        assert ask(run.client, token, 'who is playing', match_id='north-stars-0000aaaa').json()['status'] == 'answer'
        # A token belongs to its match.
        assert run.client.get(f'/lab/matches/{MATCH}/chat/{token}').status_code == 404


def test_unverified_evidence_fails_closed_and_does_not_create_offer(store):
    class Invented:
        mode = 'fixture'

        async def answer(self, *args):
            return QuestionDraft(answer_kind='match', status='answer', text='A made-up fact', evidence_ids=['event:future:1'])
    with Running(store, agent=Invented()) as run:
        token = session(run.client)
        answer = ask(run.client, token, 'what happened').json()
        assert answer['status'] == 'unsupported' and answer['offers'] == []
        assert run.client.get(f'/lab/matches/{MATCH}/chat/{token}').json()['turns'][0]['status'] == 'failed'


def test_upstream_failure_is_visible_and_no_fallback(store):
    called = []
    with Running(store) as run:
        async def unavailable(snapshot):
            raise httpx.ConnectError('Upstream unavailable')

        async def forbidden(*args):
            called.append(True)
            raise AssertionError('Agent must not run without context')
        run.service.narratives.compact = unavailable
        run.service.agent.answer = forbidden
        answer = ask(run.client, session(run.client), 'question').json()
        assert answer['status'] == 'unsupported' and not called


def test_no_model_refuses_questions_and_health_is_not_ready(store):
    with Running(store, agent=None, planner=None) as run:
        token = session(run.client)
        refused = ask(run.client, token, 'what is offside')
        assert refused.status_code == 503 and refused.json()['code'] == 'model_unavailable'
        plan = run.client.post(f'/lab/matches/{MATCH}/plan', json={'prompt': 'corners'})
        assert plan.status_code == 503
        for path in ('/health', '/ready'):
            health = run.client.get(path)
            assert health.status_code == 503 and health.json()['checks']['model'] == 'missing'
    with Running(store) as run:
        assert run.client.get('/ready').status_code == 200


def test_startup_recovers_interrupted_turn(store):
    upstream = Upstream()
    with Running(store, upstream=upstream) as run:
        token = session(run.client)
        run.service.repository.begin(token, str(uuid4()), 'Interrupted question')
        assert run.client.get(f'/lab/matches/{MATCH}/chat/{token}').json()['turns'][0]['status'] == 'pending'
    with Running(store, upstream=upstream, matches=()) as run:
        row = run.client.get(f'/lab/matches/{MATCH}/chat/{token}').json()
        assert row['turns'][0]['status'] == 'failed' and 'interrupted' in row['turns'][0]['reply']['text']


def test_statistical_draft_cannot_skip_deterministic_calculation_or_offer(store):
    class SkipsTool:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            return QuestionDraft(answer_kind='statistic', status='answer', text='I counted 999 headers myself.',
                                 statistic_request="Track Mbappe's headed shots")
    with Running(store, agent=SkipsTool()) as run:
        run.send(10)
        token = session(run.client)
        reply = ask(run.client, token, 'How many headed shots has Mbappe had?').json()
        assert reply['status'] == 'answer' and reply['answer_kind'] == 'statistic'
        assert reply['offers'][0]['value'] == 1 and reply['goal']['player_ids'] == ['mbappe']
        assert '999' not in reply['text'] and reply['evidence_ids'] == ['offer:' + reply['offers'][0]['id']]
        assert run.match().engine.count == 0
        restored = run.client.get(f'/lab/matches/{MATCH}/chat/{token}').json()['turns'][0]['reply']
        assert restored['goal'] == reply['goal']


def test_statistical_draft_uses_upstream_stat_without_compiling_or_history(store):
    class Standard:
        mode = 'fixture'

        async def answer(self, *args):
            return QuestionDraft(answer_kind='statistic', status='answer', standard_stat_id='all:shots', text='999 shots.')
    with Running(store, agent=Standard()) as run:
        async def forbidden(*args, **kwargs):
            raise AssertionError('Existing stat must not compile a rule')
        run.service.planner.plan = forbidden
        reply = ask(run.client, session(run.client), 'How many shots?').json()
        assert reply['status'] == 'answer' and reply['text'] == 'Both teams shots: 0.'
        assert reply['offers'][0]['standard_stat_id'] == reply['standard_stat_id'] == 'all:shots'


@pytest.mark.parametrize('planner_status', ['clarification', 'unsupported'])
def test_statistical_fallback_propagates_planner_clarification_or_unsupported(store, planner_status):
    from backend.agents.models import PlanOutcome

    class Statistical:
        mode = 'fixture'

        async def answer(self, *args):
            return QuestionDraft(answer_kind='statistic', status='answer', text='999 headers.', statistic_request='headers')

    class Planner:
        async def plan(self, request, context):
            assert request == 'headers'
            return PlanOutcome(status=planner_status, source='fixture', message='Which kind of header?')
    with Running(store, agent=Statistical(), planner=Planner()) as run:
        reply = ask(run.client, session(run.client), 'headers').json()
        assert reply['status'] == planner_status and reply['offers'] == [] and '999' not in reply['text']
        assert reply['text'] == ('Which kind of header?' if planner_status == 'clarification'
                                 else 'Sorry, I cannot answer that. Which kind of header?')


def test_failed_plan_and_exceptions_stay_generic(store):
    from backend.agents.models import PlanOutcome

    class Statistical:
        mode = 'fixture'

        async def answer(self, *args):
            return QuestionDraft(answer_kind='statistic', status='answer', text='?', statistic_request='headers')

    class Planner:
        calls = 0

        async def plan(self, request, context):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError('provider body must not leak')
            return PlanOutcome(status='failed', source='fixture', message='Could not validate the calculation after 3 repairs.')
    with Running(store, agent=Statistical(), planner=Planner()) as run:
        token = session(run.client)
        assert ask(run.client, token, 'headers').json()['text'] == 'Sorry, I cannot answer that from the information available.'
        assert ask(run.client, token, 'headers').json()['text'] == 'Sorry, I could not answer that. Please try again.'


def test_missing_statistic_source_does_not_accept_numerical_prose(store):
    class Unbacked:
        mode = 'fixture'

        async def answer(self, *args):
            return QuestionDraft(answer_kind='statistic', status='answer', text='999 goals.')
    with Running(store, agent=Unbacked()) as run:
        reply = ask(run.client, session(run.client), 'How many goals?').json()
        assert reply['status'] == 'unsupported' and '999' not in reply['text']


def test_followup_gets_prior_validated_goal_and_can_prepare_changed_scope(store):
    from backend.agents.models import Goal, PlanOutcome

    class Followup:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            if prompt == 'second half?':
                goal = context['history'][-1]['reply']['goal']
                assert goal['player_ids'] == ['mbappe'] and goal['bodyparts'] == ['head']
                assert goal['action_types'] == ['shot', 'shot_penalty', 'shot_freekick']
                request = 'Mbappe headed shots in the second half'
            else:
                request = 'Mbappe headed shots in the whole match'
            return QuestionDraft(answer_kind='statistic', status='answer', text='Checking.', statistic_request=request)

    class Planner:
        async def plan(self, request, context):
            goal = Goal(description=request, player_ids=('mbappe',), bodyparts=('head',),
                        action_types=('shot', 'shot_penalty', 'shot_freekick'),
                        period=2 if 'second half' in request else None)
            return PlanOutcome(status='ready', source='fixture', goal=goal, rule=goal.target_rule(context['match_id']))
    with Running(store, agent=Followup(), planner=Planner()) as run:
        run.send(10)
        token = session(run.client)
        first = ask(run.client, token, 'headed shots?').json()
        second = ask(run.client, token, 'second half?').json()
        assert first['offers'][0]['value'] == 1 and second['offers'][0]['value'] == 0
        assert second['goal']['period'] == 2 and run.match().engine.count == 0


def test_saved_replay_pages_reuse_their_bound_and_reject_bad_pages_and_matches(store):
    spec = json.loads(FixtureEventSource().content)
    spec['presets'] = []
    # Replays cut footage, so the events need a video timeline.
    spec['events'] = [{**e, 'videoSeconds': 30.0 * index} for index, e in enumerate(spec['events'])]
    upstream = Upstream()
    upstream.add(MATCH, FixtureEventSource(content=json.dumps(spec).encode()))
    with Running(store, upstream=upstream) as run:
        run.send(len(spec['events']))
        token = session(run.client)
        reply = ask(run.client, token, 'show me all the shots so far').json()
        assert reply['status'] == 'answer' and reply['replay']['clips'], reply
        path = f'/lab/matches/{MATCH}/chat/{token}'
        turn = run.client.get(path).json()['turns'][-1]
        page = run.client.get(f'{path}/turns/{turn["id"]}/replay/0').json()
        assert page['clips'] == reply['replay']['clips'] and page['observed_until'] == reply['replay']['observed_until']
        for bad in (reply['replay']['page_count'], -1):
            assert run.client.get(f'{path}/turns/{turn["id"]}/replay/{bad}').status_code == 404
        assert run.client.get(f'{path}/turns/999999/replay/0').status_code == 404
        run.client.post('/admin/matches/purge', json={'match_id': MATCH})
        assert run.client.get(f'{path}/turns/{turn["id"]}/replay/0').status_code == 404
