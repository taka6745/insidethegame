"""Question integration uses real Postgres and separate HTTP fake upstream apps."""
import asyncio
import json
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Event as ThreadEvent

import httpx
import pytest
from fastapi.testclient import TestClient
from backend.adapters.question_data import GraphQLQuestionData
from backend.agents.question_fixture import FixtureQuestionAgent
from backend.models.questions import QuestionDraft
from backend.app import create_app
from backend.fakes import create_fake
from backend.repositories.questions import QuestionRepository
from backend.services.question_snapshot import LabSnapshotProvider
from backend.services.questions import QuestionService
from test_lab_api import make_lab


def build(store, agent=None, timeout=5):
    lab = make_lab(store)
    upstreams = [create_fake('etl'), create_fake('narrative')]
    adapters = [GraphQLQuestionData('http://fake/graphql',bridge=True,transport=httpx.ASGITransport(app=app)) for app in upstreams]
    questions = QuestionService(QuestionRepository(store),LabSnapshotProvider(lab),*adapters,agent or FixtureQuestionAgent(),lab.planner,timeout=timeout)
    return lab, questions, upstreams, create_app(store,lab=lab,questions=questions)


def session(client, profile='chelsea-analytical'):
    response = client.post('/lab/chat/sessions',json={'profile_id':profile})
    assert response.status_code == 200,response.text
    return response.json()['session_token']


def ask(client, token, prompt, request_id=None):
    return client.post(f'/lab/chat/{token}/messages',json={'prompt':prompt,'request_id':request_id or str(uuid4())})


def test_standard_stats_are_upstream_and_no_custom_rule_or_history(store):
    lab, service, apps, app = build(store)
    async def forbidden(*args,**kwargs):
        raise AssertionError('Standard stats must not read events or compile rules')
    service.match_data.events = service.planner.plan = forbidden
    with TestClient(app) as client:
        for _ in range(15): client.portal.call(lab.advance)
        token = session(client)
        reply = ask(client,token,'how many Both teams shots').json()
        assert reply['status'] == 'answer',reply
        assert reply['snapshot']['match_id'] == lab.source.match_id
        assert reply['snapshot']['cursor'] == 15
        assert reply['evidence'][0]['id'] == 'stat:all:shots'
        assert reply['offers'] == []
        assert lab.engine.count == 0
        assert all(len(next(iter(a.state.question_data.snapshots.values())).events) == 15 for a in apps)


def test_one_off_offer_track_catches_up_and_shared_rule_reuse(store):
    lab, service, _, app = build(store)
    with TestClient(app) as client:
        for _ in range(10): client.portal.call(lab.advance)
        token = session(client)
        reply = ask(client,token,"Track Mbappe's headed shots").json()
        assert reply['status'] == 'answer',reply
        offer = reply['offers'][0]
        assert offer['value'] == 1
        assert lab.engine.count == 0
        for _ in range(12): client.portal.call(lab.advance)
        expected = 2  # duplicate deliveries and a corrected shot must not be double counted
        tracked = client.post(f'/lab/chat/{token}/offers/{offer["id"]}/track').json()
        assert tracked['calculation']['value'] == expected
        duplicate = client.post(f'/lab/chat/{token}/offers/{offer["id"]}/track').json()
        assert duplicate['calculation'] == tracked['calculation']
        assert lab.engine.count == 1
        other = session(client,'united-casual')
        assert client.post(f'/lab/chat/{other}/offers/{offer["id"]}/track').status_code == 404
        saved = client.get(f'/lab/chat/{token}').json()
        assert saved['offers'][0]['calculation_id'] == tracked['calculation']['id']
        client.post('/lab/reset')
        assert client.post(f'/lab/chat/{token}/offers/{offer["id"]}/track').status_code == 409


def test_retry_takeover_restore_and_new_run(store):
    lab, service, _, app = build(store)
    with TestClient(app) as client:
        token = session(client)
        identifier = str(uuid4())
        first = ask(client,token,'what is offside',identifier)
        retry = ask(client,token,'what is offside',identifier)
        assert first.json() == retry.json()
        assert ask(client,token,'different',identifier).status_code == 409
        replacement = session(client)
        assert client.get(f'/lab/chat/{token}').status_code == 409
        assert len(client.get(f'/lab/chat/{replacement}').json()['turns']) == 1
    lab2, service2, _, app2 = build(store)
    with TestClient(app2) as client:
        restored = client.get(f'/lab/chat/{replacement}')
        assert restored.status_code == 200
        assert restored.json()['turns'][0]['reply']['status'] == 'answer'
        client.post('/lab/reset')
        new = session(client)
        assert client.get(f'/lab/chat/{new}').json()['turns'] == []


def test_snapshot_does_not_change_while_model_waits_and_duplicate_busy(store):
    entered, release = ThreadEvent(), ThreadEvent()
    class Waiting:
        mode = 'fixture'
        async def answer(self,prompt,context,tools):
            entered.set()
            await asyncio.to_thread(release.wait,3)
            result = await tools.standard(['all:shots'])
            return QuestionDraft(answer_kind='match',status='answer',text=str(result['stats'][0]['value']),evidence_ids=['stat:all:shots'])
    lab,service,_,app = build(store,Waiting())
    with TestClient(app) as client, ThreadPoolExecutor() as pool:
        for _ in range(10): client.portal.call(lab.advance)
        token, identifier = session(client), str(uuid4())
        pending = pool.submit(ask,client,token,'shots',identifier)
        assert entered.wait(3)
        assert ask(client,token,'shots',identifier).status_code == 409
        assert ask(client,token,'another question').status_code == 409
        for _ in range(10): client.portal.call(lab.advance)
        release.set()
        reply = pending.result().json()
        assert reply['snapshot']['cursor'] == 10
        assert lab.position == 20


@pytest.mark.parametrize('change',['reset','takeover'])
def test_stale_model_callback_cannot_commit(store,change):
    entered,release = ThreadEvent(),ThreadEvent()
    class Waiting:
        mode='fixture'
        async def answer(self,*args):
            entered.set(); await asyncio.to_thread(release.wait,3)
            return QuestionDraft(answer_kind='match',status='answer',text='A late answer')
    lab,service,_,app=build(store,Waiting())
    with TestClient(app) as client, ThreadPoolExecutor() as pool:
        token=session(client)
        pending=pool.submit(ask,client,token,'question')
        assert entered.wait(3)
        if change=='reset': client.post('/lab/reset')
        else: session(client)
        release.set()
        assert pending.result().status_code==409
        new=session(client)
        assert all(t.get('reply',{}).get('text')!='A late answer' for t in client.get(f'/lab/chat/{new}').json()['turns'])


def test_clarification_and_prior_goal_persist_in_context(store):
    seen=[]
    class Clarifying:
        mode='fixture'
        async def answer(self,prompt,context,tools):
            seen.append(context)
            if prompt=='headers':
                return QuestionDraft(answer_kind='match',status='clarification',text='Headed shots or all recorded contacts?')
            assert context['history'][-1]['reply']['status']=='clarification'
            return QuestionDraft(answer_kind='match',status='answer',text='Understood.')
    lab,service,_,app=build(store,Clarifying())
    with TestClient(app) as client:
        token=session(client)
        assert ask(client,token,'headers').json()['status']=='clarification'
        assert ask(client,token,'all contacts').json()['status']=='answer'
        assert len(seen[1]['history'])==1


def test_wrong_snapshot_upstream_and_timeout_do_not_leave_pending(store):
    class Slow:
        mode='fixture'
        async def answer(self,*args):
            await asyncio.sleep(1)
    lab,service,_,app=build(store,Slow(),timeout=.05)
    with TestClient(app) as client:
        token=session(client)
        response=ask(client,token,'question').json()
        assert response['status']=='unsupported'
        row=client.get(f'/lab/chat/{token}').json()
        assert row['turns'][0]['status']=='failed'
        assert 'Sorry' in row['turns'][0]['reply']['text']


def test_uploaded_match_identity_no_default_fixture_leak(store):
    class Inspect:
        mode='fixture'
        async def answer(self,prompt,context,tools):
            assert context['snapshot']['match_id']=='another-match'
            assert context['teams'][0]['name']=='North Stars'
            assert all('chelsea' not in json.dumps(s).lower() for s in context['standard_stats'])
            return QuestionDraft(answer_kind='match',status='answer',text='North Stars are playing.')
    lab,service,_,app=build(store,Inspect())
    with TestClient(app) as client:
        data=json.loads(lab.source.content)
        data['match_id']='another-match'
        data['teams'][0]['name']='North Stars'
        for e in data['events']: e['matchId']='another-match'
        for preset in data['presets']: preset['rule']['match_id']='another-match'
        # Rename IDs too so no accidental default-fixture joins can pass.
        mapping={t['id']:f'team-{i}' for i,t in enumerate(data['teams'])}
        for t in data['teams']:t['id']=mapping[t['id']]
        for p in data['players']:p['team_id']=mapping[p['team_id']]
        for e in data['events']:
            if e.get('teamId') in mapping:e['teamId']=mapping[e['teamId']]
        data['presets']=[]
        result=client.post('/lab/recording',content=json.dumps(data),headers={'content-type':'application/json','x-recording-filename':'another.json'})
        assert result.status_code==200,result.text
        for _ in range(5):client.portal.call(lab.advance)
        token=session(client)
        assert ask(client,token,'who is playing').json()['status']=='answer'


def test_unverified_evidence_fails_closed_and_does_not_create_offer(store):
    class Invented:
        mode='fixture'
        async def answer(self,*args):
            return QuestionDraft(answer_kind='match',status='answer',text='A made-up fact',evidence_ids=['event:future:1'])
    lab,service,_,app=build(store,Invented())
    with TestClient(app) as client:
        token=session(client)
        answer=ask(client,token,'what happened').json()
        assert answer['status']=='unsupported'
        assert answer['offers']==[]
        assert client.get(f'/lab/chat/{token}').json()['turns'][0]['status']=='failed'


def test_upstream_failure_is_visible_and_no_fixture_fallback(store):
    lab,service,_,app=build(store)
    called=[]
    async def unavailable(snapshot):
        raise httpx.ConnectError('Upstream unavailable')
    async def forbidden(*args):
        called.append(True)
        raise AssertionError('Agent must not run without context')
    service.narratives.compact=unavailable
    service.agent.answer=forbidden
    with TestClient(app) as client:
        answer=ask(client,session(client),'question').json()
        assert answer['status']=='unsupported'
        assert not called


def test_startup_recovers_interrupted_turn(store):
    lab,service,_,app=build(store)
    with TestClient(app) as client:
        token=session(client)
        service.repository.begin(token,str(uuid4()),'Interrupted question')
        assert client.get(f'/lab/chat/{token}').json()['turns'][0]['status']=='pending'
    lab,service,_,app=build(store)
    with TestClient(app) as client:
        row=client.get(f'/lab/chat/{token}').json()
        assert row['turns'][0]['status']=='failed'
        assert 'interrupted' in row['turns'][0]['reply']['text']


def test_statistical_draft_cannot_skip_deterministic_calculation_or_offer(store):
    class SkipsTool:
        mode='fixture'
        async def answer(self,prompt,context,tools):
            return QuestionDraft(answer_kind='statistic',status='answer',text='I counted 999 headers myself.',
                                 statistic_request="Track Mbappe's headed shots")
    lab,service,_,app=build(store,SkipsTool())
    with TestClient(app) as client:
        for _ in range(10):client.portal.call(lab.advance)
        token=session(client)
        reply=ask(client,token,'How many headed shots has Mbappe had?').json()
        assert reply['status']=='answer'
        assert reply['answer_kind']=='statistic'
        assert reply['offers'][0]['value']==1
        assert reply['goal']['player_ids']==['mbappe']
        assert '999' not in reply['text']
        assert reply['evidence_ids']==['offer:'+reply['offers'][0]['id']]
        assert lab.engine.count==0
        restored=client.get(f'/lab/chat/{token}').json()['turns'][0]['reply']
        assert restored['goal']==reply['goal']


def test_statistical_draft_uses_upstream_stat_without_compiling_or_history(store):
    class Standard:
        mode='fixture'
        async def answer(self,*args):
            return QuestionDraft(answer_kind='statistic',status='answer',standard_stat_id='all:shots',text='999 shots.')
    lab,service,_,app=build(store,Standard())
    async def forbidden(*args,**kwargs):
        raise AssertionError('Existing stat must not compile or query raw events')
    service.match_data.events=service.planner.plan=forbidden
    with TestClient(app) as client:
        reply=ask(client,session(client),'How many shots?').json()
        assert reply['status']=='answer'
        assert reply['text']=='Both teams shots: 0.'
        assert reply['offers']==[]
        assert reply['standard_stat_id']=='all:shots'


@pytest.mark.parametrize('planner_status',['clarification','unsupported'])
def test_statistical_fallback_propagates_planner_clarification_or_unsupported(store,planner_status):
    from backend.agents.models import PlanOutcome
    class Statistical:
        mode='fixture'
        async def answer(self,*args):
            return QuestionDraft(answer_kind='statistic',status='answer',text='999 headers.',statistic_request='headers')
    class Planner:
        async def plan(self,request,context):
            assert request=='headers'
            return PlanOutcome(status=planner_status,source='fixture',message='Which kind of header?')
    lab,service,_,app=build(store,Statistical())
    service.planner=Planner()
    with TestClient(app) as client:
        reply=ask(client,session(client),'headers').json()
        assert reply['status']==planner_status
        assert reply['offers']==[]
        assert '999' not in reply['text']
        if planner_status=='clarification':assert reply['text']=='Which kind of header?'
        else:assert reply['text'].startswith('Sorry')


def test_missing_statistic_source_does_not_accept_numerical_prose(store):
    class Unbacked:
        mode='fixture'
        async def answer(self,*args):
            return QuestionDraft(answer_kind='statistic',status='answer',text='999 goals.')
    lab,service,_,app=build(store,Unbacked())
    with TestClient(app) as client:
        reply=ask(client,session(client),'How many goals?').json()
        assert reply['status']=='unsupported'
        assert '999' not in reply['text']


def test_followup_gets_prior_validated_goal_and_can_prepare_changed_scope(store):
    from backend.agents.models import Goal,PlanOutcome
    class Followup:
        mode='fixture'
        async def answer(self,prompt,context,tools):
            if prompt=='second half?':
                goal=context['history'][-1]['reply']['goal']
                assert goal['player_ids']==['mbappe']
                assert goal['body_part']=='head'
                assert goal['event_types']==['shot','goal']
                request='Mbappe headed shots in the second half'
            else:request='Mbappe headed shots in the whole match'
            return QuestionDraft(answer_kind='statistic',status='answer',text='Checking.',statistic_request=request)
    class Planner:
        async def plan(self,request,context):
            goal=Goal(description=request,player_ids=('mbappe',),body_part='head',event_types=('shot','goal'),period=2 if 'second half' in request else None)
            return PlanOutcome(status='ready',source='fixture',goal=goal,rule=goal.target_rule(context['match_id']))
    lab,service,_,app=build(store,Followup());service.planner=Planner()
    with TestClient(app) as client:
        for _ in range(10):client.portal.call(lab.advance)
        token=session(client)
        first=ask(client,token,'headed shots?').json()
        second=ask(client,token,'second half?').json()
        assert first['offers'][0]['value']==1
        assert second['offers'][0]['value']==0
        assert second['goal']['period']==2
        assert lab.engine.count==0
