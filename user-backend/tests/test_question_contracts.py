"""Required-source decisions and generic omitted-request recovery."""
import asyncio
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from backend.agents.question_contracts import QuestionDecision
from backend.models.questions import QuestionDraft
from backend.services.question_answers import resolve_answer


@pytest.mark.parametrize('decision',[{'route':'custom_stat'}, {'route':'standard_stat'}, {'route':'prepared_stat'}, {'route':'custom_stat','request':None}])
def test_statistical_wire_branch_requires_its_source(decision):
    with pytest.raises(ValidationError):QuestionDecision.model_validate({'decision':decision})


def test_custom_wire_has_no_place_for_invented_count_prose():
    with pytest.raises(ValidationError):
        QuestionDecision.model_validate({'decision':{'route':'custom_stat','request':'A metric','text':'999 events'}})
    draft=QuestionDecision.model_validate({'decision':{'route':'custom_stat','request':'A fully resolved metric'}}).draft(None)
    assert draft.answer_kind=='statistic'
    assert draft.statistic_request=='A fully resolved metric'


def test_prepared_wire_id_must_exist_in_current_question():
    wire=QuestionDecision.model_validate({'decision':{'route':'prepared_stat','offer_id':'foreign'}})
    with pytest.raises(ValueError,match='does not exist'):wire.draft(SimpleNamespace(offers=[]))


def test_missing_request_can_be_recovered_from_original_dialogue_without_prose():
    class Tools:
        original_prompt='What about the second half?'
        offers=[]
        async def prepare_original(self):
            self.offers=[{'id':'actual','label':'The clarified metric','value':2}]
            return {'status':'ready','offer_id':'actual'}
    result=asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic',status='answer',text='999'),Tools()))
    assert result.text=='The clarified metric: 2.'
    assert result.evidence_ids==['offer:actual']


def test_missing_request_recovery_preserves_clarification():
    class Tools:
        original_prompt='What about him?'
        async def prepare_original(self):return {'status':'clarification','message':'Which player?'}
    result=asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic',status='answer',text='999'),Tools()))
    assert result.status=='clarification' and result.text=='Which player?'


def test_explicit_inclusive_event_boundary_is_translated_without_dropping_exact_event():
    from backend.services.question_tools import QuestionTools
    from backend.models.questions import MatchSnapshot,SnapshotInput
    from backend.fake_question_data import snapshot_id
    from backend.fakes import create_fake
    from backend.adapters.question_data import GraphQLQuestionData
    import httpx
    from backend.models.events import Event
    data=SnapshotInput(snapshot=MatchSnapshot(id='',run_id='run',match_id='m',recording_hash='h',cursor=3,clock_seconds=601,period=1,captured_at='test'),
        teams=[],players=[],data_reference={},events=[Event(event_id=str(second),match_id='m',event_type='shot',match_time_seconds=second) for second in (599,600,601)])
    data.snapshot.id=snapshot_id(data)
    adapter=GraphQLQuestionData('http://fake/graphql',bridge=True,transport=httpx.ASGITransport(app=create_fake('etl')))
    async def run():
        await adapter.capture(data)
        tools=QuestionTools(data,adapter,None,None,[],{},[])
        exclusive=await tools.events(end=600)
        inclusive=await tools.events(end=600,end_inclusive=True)
        assert [e['match_time_seconds'] for e in exclusive['items']]==[599]
        assert [e['match_time_seconds'] for e in inclusive['items']]==[599,600]
    asyncio.run(run())


def _offer(identifier, value):
    return {'id':identifier,'label':f'Stat {identifier}','value':value,'goal':{'description':f'Goal {identifier}'}}


@pytest.mark.parametrize('last_status',['ready','unsupported','clarification'])
def test_final_prepared_selection_uses_a_even_after_b_result(last_status):
    tools=SimpleNamespace(offers=[_offer('a',2),_offer('b',7)],goal={'description':'Goal b'},
                          prepared_results={'Request B':{'status':last_status,'offer_id':'b'}})
    draft=QuestionDraft(answer_kind='statistic',status='answer',selected_offer_id='a',text='Not authoritative')
    result=asyncio.run(resolve_answer(draft,tools))
    assert result.text=='Stat a: 2.'
    assert result.selected_offer_id=='a'
    assert tools.offers==[_offer('a',2)]
    assert tools.goal=={'description':'Goal a'}


def test_final_custom_request_b_cannot_reuse_prepared_a():
    class Tools:
        offers=[_offer('a',2)]
        goal={'description':'Goal a'}
        prepared_results={'Request A':{'status':'ready','offer_id':'a'}}
        calls=[]
        async def prepare(self,request):
            self.calls.append(request)
            self.offers.append(_offer('b',7))
            return {'status':'ready','offer_id':'b'}
    tools=Tools()
    result=asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic',status='answer',statistic_request='Request B',text='Ignored'),tools))
    assert tools.calls==['Request B']
    assert result.text=='Stat b: 7.'
    assert tools.offers==[_offer('b',7)]
    assert tools.goal=={'description':'Goal b'}


def test_exact_prepared_request_reuses_only_its_corresponding_offer():
    class Tools:
        offers=[_offer('a',2),_offer('b',7)]
        prepared_results={'Request A':{'status':'ready','offer_id':'a'},'Request B':{'status':'ready','offer_id':'b'}}
        async def prepare(self,request):raise AssertionError('An exact request already has a result')
    tools=Tools()
    result=asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic',status='answer',statistic_request='Request A',text='Ignored'),tools))
    assert result.selected_offer_id=='a'
    assert tools.offers==[_offer('a',2)]


def test_original_recovery_keeps_constraints_after_900_characters():
    from backend.services.question_tools import QuestionTools
    from backend.models.questions import MatchSnapshot,SnapshotInput
    from backend.agents.models import PlanOutcome
    original='Track this statistic. '+('Context about the request. '*40)+' Only after minute 60.'
    assert 900<len(original)<2000
    class Planner:
        async def plan(self,request,context,history):
            assert request=='For that player too'
            assert history[0]['content']==original
            assert history[0]['content'].endswith('Only after minute 60.')
            return PlanOutcome(status='clarification',source='fixture',message='Which player?')
    payload=SnapshotInput(snapshot=MatchSnapshot(id='s',run_id='r',match_id='m',recording_hash='h',cursor=0,captured_at='test'),events=[],teams=[],players=[],data_reference={})
    tools=QuestionTools(payload,None,None,Planner(),[],{},[{'user':original,'reply':{'text':'Which player?'}}])
    tools.original_prompt='For that player too'
    assert asyncio.run(tools.prepare_original())['status']=='clarification'


def test_original_recovery_asks_to_restate_instead_of_cutting_long_goal():
    from backend.services.question_tools import QuestionTools
    class Planner:
        async def plan(self,*args,**kwargs):raise AssertionError('Do not send a truncated semantic goal')
    tools=QuestionTools(None,None,None,Planner(),[],{},[{'user':'Metric','reply':{'goal':{'description':'x'*2500}}}])
    tools.original_prompt='Second half'
    result=asyncio.run(tools.prepare_original())
    assert result['status']=='clarification'
    assert 'restate' in result['message']
