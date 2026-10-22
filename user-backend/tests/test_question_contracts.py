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


def test_explicit_inclusive_action_boundary_is_translated_without_dropping_exact_action():
    from backend.services.question_tools import QuestionTools
    from backend.models.actions import SpadlAction
    from backend.models.questions import MatchSnapshot,SnapshotInput
    from backend.adapters.match_data import EtlDabMatchData
    actions=[SpadlAction(match_id='m',action_id=i,period=1,match_time_seconds=second,team_id='t',action_type='shot',
                         result='fail',bodypart='foot',start_x=90.0,start_y=34.0,end_x=105.0,end_y=34.0,
                         start_zone='opp_box',end_zone='opp_box',seq=i+1,final_seq=i+1)
             for i,second in enumerate((599,600,601))]
    data=SnapshotInput(snapshot=MatchSnapshot.at('m',3,None,'test'),teams=[],players=[],data_reference={},events=[],
                       actions=actions)
    match=SimpleNamespace(actions_at=lambda seq: [a for a in actions if a.final_seq<=seq])
    adapter=EtlDabMatchData(None,SimpleNamespace(get=lambda match_id: match))
    async def run():
        tools=QuestionTools(data,adapter,None,None,[],{},[])
        exclusive=await tools.actions(end=600)
        inclusive=await tools.actions(end=600,end_inclusive=True)
        assert [e['match_time_seconds'] for e in exclusive['items']]==[599]
        assert [e['match_time_seconds'] for e in inclusive['items']]==[599,600]
        assert inclusive['items'][0]['evidence_id']=='action:a0' and 'start_x' not in inclusive['items'][0]
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
    payload=SnapshotInput(snapshot=MatchSnapshot.at('m',0,None,'test'),events=[],teams=[],players=[],data_reference={})
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


def test_standard_percentage_keeps_unit_in_answer_and_track_offer():
    from backend.models.stat_offers import stat_answer
    stat = {'id': 'home:possession', 'label': 'Chelsea possession', 'value': 35.9,
            'unit': '%', 'available': True, 'complete': True}
    tools = SimpleNamespace(stats=[stat], offers=[], goal=None,
                            payload=SimpleNamespace(snapshot=SimpleNamespace(id='snapshot', match_id='match')))
    result = asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic', status='answer',
        standard_stat_id=stat['id'], text='Ignored'), tools))
    assert result.text == 'Chelsea possession: 35.9%.'
    assert tools.offers[0]['unit'] == '%'
    assert stat_answer(tools.offers[0]) == result.text
