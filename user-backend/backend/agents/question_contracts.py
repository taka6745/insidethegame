"""Required source branches keep statistical prose out of the answer contract."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from backend.models.questions import QuestionDraft
from backend.models.clarifications import FollowUpQuestion

class Wire(BaseModel):
    model_config = ConfigDict(extra='forbid')

class StandardStat(Wire):
    route: Literal['standard_stat']
    standard_stat_id: str = Field(min_length=1,max_length=200)

class CustomStat(Wire):
    route: Literal['custom_stat']
    request: str = Field(min_length=1,max_length=2000)

class PreparedStat(Wire):
    route: Literal['prepared_stat']
    offer_id: str = Field(min_length=1,max_length=100)

class MatchAnswer(Wire):
    route: Literal['match']
    text: str = Field(min_length=1,max_length=1800)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)

class FootballAnswer(Wire):
    route: Literal['football']
    text: str = Field(min_length=1,max_length=1800)

class AskClarification(FollowUpQuestion):
    route: Literal['clarification']
    topic: Literal['statistic','match','football']
    question: str = Field(min_length=1,max_length=500)

class Unsupported(Wire):
    route: Literal['unsupported']

class QuestionDecision(Wire):
    decision: StandardStat | CustomStat | PreparedStat | MatchAnswer | FootballAnswer | AskClarification | Unsupported

    def draft(self,tools):
        decision=self.decision
        if isinstance(decision,StandardStat):
            return QuestionDraft(answer_kind='statistic',status='answer',standard_stat_id=decision.standard_stat_id,text='Checking the recorded statistic.')
        if isinstance(decision,CustomStat):
            return QuestionDraft(answer_kind='statistic',status='answer',statistic_request=decision.request,text='Checking the requested statistic.')
        if isinstance(decision,PreparedStat):
            if decision.offer_id not in {o['id'] for o in tools.offers}:
                raise ValueError('Prepared statistic does not exist in this question')
            return QuestionDraft(answer_kind='statistic',status='answer',selected_offer_id=decision.offer_id,text='Statistic calculated.',evidence_ids=['offer:'+decision.offer_id])
        if isinstance(decision,MatchAnswer):
            if any(identifier not in tools.evidence for identifier in decision.evidence_ids):
                raise ValueError('Match answer cites unavailable evidence')
            return QuestionDraft(answer_kind='match',status='answer',text=decision.text,evidence_ids=decision.evidence_ids)
        if isinstance(decision,FootballAnswer):
            return QuestionDraft(answer_kind='football',status='answer',text=decision.text)
        if isinstance(decision,AskClarification):
            return QuestionDraft(answer_kind=decision.topic,status='clarification',text=decision.question,
                clarification=decision.model_dump(include={'question', 'options', 'allow_free_text'}))
        return QuestionDraft(answer_kind='match',status='unsupported',text='Sorry, I cannot answer that.')
