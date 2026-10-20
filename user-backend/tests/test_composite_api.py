"""Composite offers and follow-up choices cross the actual API/Postgres boundary."""
import pytest
from fastapi.testclient import TestClient
from backend.agents.models import Goal, PlanOutcome, Clarification
from backend.models.questions import QuestionDraft
from test_questions import build, session, ask


def completion_goal():
    return Goal(description='Chelsea pass completion after 60 minutes', operation='percentage', inputs=[
        {'description':'Completed Chelsea passes','event_types':['pass'],'team_ids':['chelsea'],
         'outcome':'success','from_seconds':3600},
        {'description':'Resolved Chelsea passes','event_types':['pass'],'team_ids':['chelsea'],
         'outcomes':['success','failure'],'from_seconds':3600}])


class StatAgent:
    mode = 'fixture'
    async def answer(self,prompt,context,tools):
        tools.original_prompt = prompt
        return QuestionDraft(answer_kind='statistic',status='answer',text='Checking the statistic.')


class CompositePlanner:
    async def plan(self,prompt,context,history=None):
        goal = completion_goal()
        return PlanOutcome(status='ready',source='fixture',goal=goal,rule=goal.target_rule(context['match_id']))


def test_offer_track_live_reuse_restart_and_untrack(store):
    lab, service, _, app = build(store,StatAgent())
    service.planner = CompositePlanner()
    with TestClient(app) as client:
        token = session(client)
        reply = ask(client,token,'Chelsea completion since 60 minutes').json()
        assert reply['status'] == 'answer',reply
        offer = reply['offers'][0]
        assert offer['unit'] == '%' and offer['value'] is None
        assert 'None' not in reply['text'] and lab.engine.count == 0
        tracked = client.post(f'/lab/chat/{token}/offers/{offer["id"]}/track').json()['calculation']
        assert tracked['value'] is None and tracked['available'] is False
        other = session(client,'united-casual')
        other_offer = ask(client,other,'Chelsea completion since 60 minutes').json()['offers'][0]
        client.post(f'/lab/chat/{other}/offers/{other_offer["id"]}/track').raise_for_status()
        assert lab.engine.count == 1 and lab.engine.leaf_count == 2
        for _ in lab.source.events:
            client.portal.call(lab.advance)
        final = client.get('/lab/state').json()['calculations'][0]
        # The fixture has one successful Chelsea pass at exactly 60:00.
        assert final['value'] == 100 and final['unit'] == '%'
        assert final['version'] > tracked['version']
    restored, questions, _, restored_app = build(store,StatAgent())
    with TestClient(restored_app) as client:
        value = client.get('/lab/state').json()['calculations'][0]
        assert value == final
        saved = client.get(f'/lab/chat/{token}').json()
        assert saved['offers'][0]['calculation_id'] == final['id']
        questions.repository.untrack(token,final['id'])
        assert not client.get(f'/lab/chat/{token}').json()['offers'][0].get('calculation_id')
        assert client.get(f'/lab/chat/{other}').json()['offers'][0]['calculation_id'] == final['id']


@pytest.mark.parametrize('answer',['Pass completion','Successful passes as a percentage of resolved passes'])
def test_planner_clarification_choices_free_text_and_previous_constraints(store, answer):
    class Planner:
        async def plan(self,prompt,context,history=None):
            if not history:
                return PlanOutcome(status='clarification',source='fixture',message='Which measure?',
                    clarification=Clarification(question='Which measure?',options=['Pass count','Pass completion']))
            assert history[0]['content'] == 'Chelsea passing since minute 60'
            assert 'Pass completion' in history[1]['content']
            assert prompt in {'Pass completion','Successful passes as a percentage of resolved passes'}
            return await CompositePlanner().plan(prompt,context)
    lab, service, _, app = build(store,StatAgent())
    service.planner = Planner()
    with TestClient(app) as client:
        token = session(client)
        reply = ask(client,token,'Chelsea passing since minute 60').json()
        assert reply['clarification'] == {'question':'Which measure?',
            'options':['Pass count','Pass completion'],'allow_free_text':True}
        assert reply['offers'] == []
        assert client.get(f'/lab/chat/{token}').json()['turns'][0]['reply']['clarification'] == reply['clarification']
        answered = ask(client,token,answer).json()
        assert answered['status'] == 'answer' and answered['clarification'] is None
        assert all(item['from_seconds'] == 3600 for item in answered['goal']['inputs'])


def test_direct_question_agent_clarification_roundtrip(store):
    class Direct:
        mode='fixture'
        async def answer(self,prompt,context,tools):
            return QuestionDraft(answer_kind='match',status='clarification',text='Which side?',
                clarification={'question':'Which side?','options':['Chelsea','United'],'allow_free_text':True})
    _,_,_,app = build(store,Direct())
    with TestClient(app) as client:
        token=session(client)
        result=ask(client,token,'How are they doing?').json()
        assert result['clarification']['options'] == ['Chelsea','United']
        assert result['offers'] == []


def test_admission_limit_reuses_existing_and_rejects_before_backfill(store):
    from test_lab_api import make_lab
    from backend.app import create_app
    lab = make_lab(store)
    lab.max_calculations = 1
    with TestClient(create_app(store,lab=lab)) as client:
        definition = completion_goal().target_rule(lab.source.match_id).model_dump(mode='json')
        response = client.post('/lab/calculations',json={'rule':definition,'label':'Completion'})
        assert response.status_code == 201
        assert client.post('/lab/calculations',json={'rule':definition,'label':'Same'}).status_code == 201
        calls = []
        original = lab.source.history
        def counted(position):
            calls.append(position)
            return original(position)
        lab.source.history = counted
        other = {'match_id':lab.source.match_id,'operation':'count','predicates':[]}
        denied = client.post('/lab/calculations',json={'rule':other,'label':'New'})
        assert denied.status_code == 409 and denied.json()['code'] == 'calculation_capacity'
        assert calls == [] and lab.engine.count == 1
