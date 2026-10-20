"""Pure recap schedule and snapshot/adapter contract checks."""
import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from backend.models.events import Event
from backend.models.questions import MatchSnapshot, SnapshotInput
from backend.fake_question_data import FakeQuestionData, observed_events, snapshot_id, standard_stats
from backend.fake_recaps import build_recaps
from backend.adapters.question_data import GraphQLQuestionData
from backend.fakes import create_fake
from backend.agents.question import QuestionAgent
from backend.adapters.llm import LocalJsonModel


def payload(minute=90):
    events=[Event(event_id=str(i),match_id='m',event_type='pass',team_id='a',match_time_seconds=i*60,period=1 if i<45 else 2) for i in range(minute+1)]
    result=SnapshotInput(snapshot=MatchSnapshot(id='',run_id='run',match_id='m',recording_hash='hash',cursor=len(events),clock_seconds=minute*60,period=2 if minute>=45 else 1,captured_at=datetime.now(timezone.utc).isoformat()),
                         events=events,teams=[{'id':'a','name':'A'},{'id':'b','name':'B'}],players=[],data_reference={})
    result.snapshot.id=snapshot_id(result)
    return result


@pytest.mark.parametrize('minute',[0,1,10,11,25,45,90])
def test_compact_schedule_no_overlap_and_retains_children(minute):
    data=payload(minute)
    recaps=build_recaps(data,observed_events(data.events))
    rows=recaps['blocks']
    assert [r['start_seconds'] for r in rows]==[0]+[r['end_seconds'] for r in rows[:-1]] if rows else minute==0
    if rows:assert rows[-1]['end_seconds']==minute*60
    assert len([r for r in rows if r['tier']=='earlier'])<=1
    assert len([r for r in rows if r['tier']=='five-minute'])<=3
    assert len([r for r in rows if r['tier']=='minute'])<=10
    if minute>=11:assert len([r for r in rows if r['tier']=='minute'])>=6
    archive={r['id']:r for r in recaps['archive']}
    for row in recaps['archive']:
        for child in row['child_ids']:
            assert archive[child]['superseded_by']==row['id']
    assert len([r for r in archive.values() if r['tier']=='minute'])==minute


def test_old_snapshot_keeps_then_active_children_and_no_future_events():
    old,new=payload(10),payload(11)
    a=build_recaps(old,old.events)
    b=build_recaps(new,new.events)
    assert a['blocks'][0]['tier']=='minute'
    assert b['blocks'][0]['tier']=='five-minute'
    assert a['blocks'][0]['superseded_by'] is None
    assert all(r['created_cursor']<=old.snapshot.cursor for r in a['archive'])


def test_corrections_tombstones_and_key_ledger_are_not_score():
    data=payload(1)
    goal=Event(event_id='goal',match_id='m',event_type='goal',team_id='a',match_time_seconds=30)
    deleted=goal.model_copy(update={'revision':2,'deleted':True})
    data.events += [goal,goal,deleted]
    live=observed_events(data.events)
    assert not any(e.event_id=='goal' for e in live)
    stats=standard_stats(data,live)
    assert next(s for s in stats if s['id']=='a:goals')['value']==0
    ledger=build_recaps(data,live)['key_events']
    assert any(e['event_id']=='goal' and e['deleted'] for e in ledger)


def test_fake_graphql_paging_and_archive_filters():
    app=create_fake('narrative');data=payload(90)
    with TestClient(app) as client:
        assert client.post('/dev/question-snapshots',json=data.model_dump()).status_code==200
        response=client.post('/graphql',json={'query':'query($id:ID!){questionData(snapshotId:$id,operation:"recaps",tier:"minute",limit:10,offset:0)}','variables':{'id':data.snapshot.id}}).json()
        page=response['data']['questionData']
        assert len(page['items'])==10 and page['has_more']
        assert all(r['tier']=='minute' for r in page['items'])
        assert page['items'][0]['superseded_by']
        data.events=[]
        assert client.post('/dev/question-snapshots',json=data.model_dump()).status_code==422


def test_adapter_rejects_wrong_match_or_snapshot():
    data=payload(1)
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'data':{'questionData':{'snapshot_id':data.snapshot.id,'match_id':'wrong','complete':True}}}))
    adapter=GraphQLQuestionData('http://fake/graphql',transport=transport)
    with pytest.raises(ValueError,match='Wrong upstream'):
        asyncio.run(adapter.stats(data.snapshot))


def test_native_framework_calls_tool_then_validates_reply():
    requests=[]
    def respond(request):
        body=json.loads(request.content);requests.append(body)
        if len(requests)==1:
            return httpx.Response(200,json={'id':'route','object':'chat.completion','created':0,'model':'test','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps({'route':'match'})}}]})
        if len(requests)==2:
            return httpx.Response(200,json={'id':'r1','object':'chat.completion','created':0,'model':'test','choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'call_1','type':'function','function':{'name':'read_standard_stats','arguments':'{"ids":["all:shots"]}'}}]}}]})
        assert any(m['role']=='tool' for m in body['messages'])
        return httpx.Response(200,json={'id':'r2','object':'chat.completion','created':0,'model':'test','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps({'decision':{'route':'standard_stat','standard_stat_id':'all:shots'}})}}]})
    class Tools:
        async def standard(self,ids):
            assert ids==['all:shots']
            return {'stats':[{'id':'all:shots','value':4}]}
    agent=QuestionAgent(LocalJsonModel('http://fake/v1','test',transport=httpx.MockTransport(respond)))
    reply=asyncio.run(agent.answer('How is the team attacking?',{},Tools()))
    assert reply.standard_stat_id=='all:shots'
    assert len(requests)==3
    assert not requests[0].get('tools')
    assert {t['function']['name'] for t in requests[1]['tools']}=={'read_standard_stats','search_events','read_recaps','prepare_stat'}


def test_unknown_event_categories_entities_and_tiers_are_unavailable_not_zero():
    from backend.services.question_tools import QuestionTools
    class NeverRead:
        async def events(self,*args,**kwargs):
            raise AssertionError('Unsupported request must not become an empty page')
        async def recaps(self,*args,**kwargs):
            raise AssertionError('Unsupported tier must not become an empty page')
    tools=QuestionTools(payload(1),NeverRead(),NeverRead(),None,[],{'available_tiers':['minute']},[])
    for request in ({'event_type':'heartbeat'}, {'player_id':'not-in-match'}, {'period':9}):
        assert asyncio.run(tools.events(**request))['unavailable']
    assert asyncio.run(tools.recaps(tier='imagined-tier'))['unavailable']


def test_event_period_filter_is_applied_before_counting_and_pagination():
    app=create_fake('etl');data=payload(90)
    adapter=GraphQLQuestionData('http://fake/graphql',bridge=True,transport=httpx.ASGITransport(app=app))
    async def run():
        await adapter.capture(data)
        result=await adapter.events(data.snapshot,period=2,offset=0,limit=10)
        assert result['total']==46
        assert result['has_more']
        assert len(result['items'])==10
        assert all(e['period']==2 for e in result['items'])
    asyncio.run(run())


def test_question_answer_kind_is_required_in_native_output_schema():
    from backend.models.questions import QuestionDraft
    from pydantic import ValidationError
    assert 'answer_kind' in QuestionDraft.model_json_schema()['required']
    with pytest.raises(ValidationError):
        QuestionDraft.model_validate({'status':'answer','text':'Unclassified numeric answer'})
