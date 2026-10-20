"""Question contracts: snapshots freeze deliveries, not just the football clock."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .clarifications import FollowUpQuestion
from .events import DETAIL_FIELDS, Event
from .recording import MAX_RECORDING_EVENTS

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class MatchSnapshot(Strict):
    id: str
    run_id: str
    match_id: str
    recording_hash: str
    cursor: int = Field(ge=0)
    clock_seconds: int | None = None
    period: int | None = None
    captured_at: str

class SnapshotInput(Strict):
    snapshot: MatchSnapshot
    events: list[Event] = Field(max_length=MAX_RECORDING_EVENTS)
    teams: list[dict] = Field(max_length=2)
    players: list[dict] = Field(max_length=1000)
    data_reference: dict

    def identity_dump(self):
        """Hashed snapshot content; must match ETL's SnapshotInput.identity_dump."""
        return self.model_dump(mode='json', exclude={'events': {'__all__': set(DETAIL_FIELDS)}})

class ReplayItem(Strict):
    source_id: str = Field(min_length=1, max_length=120)
    kind: Literal['event', 'key_moment']
    caption: str = Field(min_length=1, max_length=120)
    lead_in: Literal['short', 'normal', 'long', 'move'] = 'normal'

class QuestionDraft(Strict):
    answer_kind: Literal['football', 'match', 'statistic', 'replay']
    standard_stat_id: str | None = Field(default=None, max_length=200)
    selected_offer_id: str | None = Field(default=None, max_length=100)
    statistic_request: str | None = Field(default=None, min_length=1, max_length=2000)
    status: Literal['answer', 'clarification', 'unsupported']
    text: str = Field(min_length=1, max_length=1800)
    clarification: FollowUpQuestion | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    replay_items: list[ReplayItem] = Field(default_factory=list, max_length=36)  # replay_clips.MAX_ITEMS
    refine_offer: str | None = Field(default=None, max_length=200)

    @model_validator(mode='after')
    def follow_up(self):
        if self.status == 'clarification':
            if self.clarification is None:
                self.clarification = FollowUpQuestion(question=self.text)
            self.text = self.clarification.question
        elif self.clarification is not None:
            raise ValueError('Only clarification replies may carry a follow-up question')
        return self

class QuestionReply(QuestionDraft):
    snapshot: MatchSnapshot
    offers: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    mode: Literal['fixture', 'local']
    goal: dict | None = None
    replay: dict | None = None
    # Token counts, model calls and seconds for this answer; no model or provider identity.
    usage: dict | None = None
