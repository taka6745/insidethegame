"""Composite offers and follow-up choices cross the actual API/Postgres boundary."""
import pytest

from backend.agents.models import Clarification, Goal, PlanOutcome
from backend.models.questions import QuestionDraft
from harness import MATCH, Running, Upstream, ask, session

CHAT = f'/lab/matches/{MATCH}/chat'


def completion_goal():
    return Goal(description='Riverton Rovers pass completion after 60 minutes', operation='percentage', inputs=[
        {'description': 'Completed Riverton Rovers passes', 'action_types': ['pass'], 'team_ids': ['riverton'],
         'results': ['success'], 'from_seconds': 3600},
        {'description': 'All Riverton Rovers passes', 'action_types': ['pass'], 'team_ids': ['riverton'],
         'from_seconds': 3600}])


class StatAgent:
    mode = 'fixture'

    async def answer(self, prompt, context, tools):
        tools.original_prompt = prompt
        return QuestionDraft(answer_kind='statistic', status='answer', text='Checking the statistic.')


class CompositePlanner:
    async def plan(self, prompt, context, history=None):
        goal = completion_goal()
        return PlanOutcome(status='ready', source='fixture', goal=goal, rule=goal.target_rule(context['match_id']))


def test_offer_track_live_reuse_restart_and_untrack(store):
    upstream = Upstream()
    with Running(store, agent=StatAgent(), planner=CompositePlanner(), upstream=upstream) as run:
        token = session(run.client)
        reply = ask(run.client, token, 'Riverton Rovers completion since 60 minutes').json()
        assert reply['status'] == 'answer', reply
        offer = reply['offers'][0]
        assert offer['unit'] == '%' and offer['value'] is None
        assert 'None' not in reply['text'] and run.match().engine.count == 0
        tracked = run.client.post(f'{CHAT}/{token}/offers/{offer["id"]}/track').json()['calculation']
        assert tracked['value'] is None and tracked['available'] is False
        other = session(run.client, profile='united-casual')
        other_offer = ask(run.client, other, 'Riverton Rovers completion since 60 minutes').json()['offers'][0]
        run.client.post(f'{CHAT}/{other}/offers/{other_offer["id"]}/track').raise_for_status()
        assert run.match().engine.count == 1 and run.match().engine.leaf_count == 2
        run.send(35)
        final = run.client.get(f'/lab/matches/{MATCH}/state').json()['calculations'][0]
        # The fixture has one successful Riverton Rovers pass at exactly 60:00.
        assert final['value'] == 100 and final['unit'] == '%'
        assert final['version'] > tracked['version']
    with Running(store, agent=StatAgent(), upstream=upstream, matches=()) as run:
        # A restart recounts ETL's SPADL actions: same value, a delivery version that only moves forward.
        restored = run.client.get(f'/lab/matches/{MATCH}/state').json()['calculations'][0]
        assert {**restored, 'version': 0} == {**final, 'version': 0} and restored['version'] >= final['version']
        assert run.client.get(f'{CHAT}/{token}').json()['offers'][0]['calculation_id'] == final['id']
        run.service.repository.untrack(token, final['id'])
        assert not run.client.get(f'{CHAT}/{token}').json()['offers'][0].get('calculation_id')
        assert run.client.get(f'{CHAT}/{other}').json()['offers'][0]['calculation_id'] == final['id']


@pytest.mark.parametrize('answer', ['Pass completion', 'Successful passes as a percentage of resolved passes'])
def test_planner_clarification_choices_free_text_and_previous_constraints(store, answer):
    class Planner:
        async def plan(self, prompt, context, history=None):
            if not history:
                return PlanOutcome(status='clarification', source='fixture', message='Which measure?',
                                   clarification=Clarification(question='Which measure?', options=['Pass count', 'Pass completion']))
            assert history[0]['content'] == 'Riverton Rovers passing since minute 60'
            assert 'Pass completion' in history[1]['content']
            return await CompositePlanner().plan(prompt, context)
    with Running(store, agent=StatAgent(), planner=Planner()) as run:
        token = session(run.client)
        reply = ask(run.client, token, 'Riverton Rovers passing since minute 60').json()
        assert reply['clarification'] == {'question': 'Which measure?', 'options': ['Pass count', 'Pass completion'],
                                          'allow_free_text': True}
        assert reply['offers'] == []
        assert run.client.get(f'{CHAT}/{token}').json()['turns'][0]['reply']['clarification'] == reply['clarification']
        answered = ask(run.client, token, answer).json()
        assert answered['status'] == 'answer' and answered['clarification'] is None
        assert all(item['from_seconds'] == 3600 for item in answered['goal']['inputs'])


def test_direct_question_agent_clarification_roundtrip(store):
    class Direct:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            return QuestionDraft(answer_kind='match', status='clarification', text='Which side?',
                                 clarification={'question': 'Which side?', 'options': ['Riverton Rovers', 'United'],
                                                'allow_free_text': True})
    with Running(store, agent=Direct()) as run:
        result = ask(run.client, session(run.client), 'How are they doing?').json()
        assert result['clarification']['options'] == ['Riverton Rovers', 'United'] and result['offers'] == []


def test_admission_limit_reuses_existing_and_rejects_before_backfill(store):
    with Running(store, max_calculations=1) as run:
        definition = completion_goal().target_rule(MATCH).model_dump(mode='json')
        path = f'/lab/matches/{MATCH}/calculations'
        assert run.client.post(path, json={'rule': definition, 'label': 'Completion'}).status_code == 201
        assert run.client.post(path, json={'rule': definition, 'label': 'Same'}).status_code == 201
        other = {'match_id': MATCH, 'operation': 'count', 'predicates': []}
        denied = run.client.post(path, json={'rule': other, 'label': 'New'})
        assert denied.status_code == 409 and denied.json()['code'] == 'calculation_capacity'
        assert run.match().engine.count == 1
        wrong = run.client.post(path, json={'rule': {**other, 'match_id': 'another-match'}, 'label': 'New'})
        assert wrong.status_code == 422 and wrong.json()['code'] == 'wrong_match'
