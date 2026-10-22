"""Question contracts: a snapshot is one (matchId, seq) point, not just the football clock."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .clarifications import FollowUpQuestion
from .actions import MAX_MATCH_ACTIONS, SpadlAction
from .events import MAX_MATCH_EVENTS, Event

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class MatchSnapshot(Strict):
    """`id` = `{match_id}:{seq}`; data at seq is immutable once ETL's watermark has reached it."""
    id: str
    match_id: str
    seq: int = Field(ge=0)
    clock_seconds: int | None = None
    period: int | None = None
    video_seconds: float | None = None
    captured_at: str

    @classmethod
    def at(cls, match_id, seq, event=None, captured_at=''):
        """The snapshot at `seq`, its clock read from the canonical event at that seq."""
        return cls(id=f'{match_id}:{seq}', match_id=match_id, seq=seq, captured_at=captured_at,
                   period=event.period if event else None,
                   clock_seconds=event.match_time_seconds if event else None,
                   video_seconds=event.video_seconds if event else None)

class SnapshotInput(Strict):
    snapshot: MatchSnapshot
    events: list[Event] = Field(max_length=MAX_MATCH_EVENTS)  # Received canonical events: clock and ticker only.
    actions: list[SpadlAction] = Field(default_factory=list, max_length=MAX_MATCH_ACTIONS)  # finalSeq <= seq.
    teams: list[dict] = Field(max_length=2)
    players: list[dict] = Field(max_length=1000)
    data_reference: dict

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
    # Set when the question named another live match of the demo: the answer comes from that match, at its own
    # position (services/cross_match.header).
    other_match: dict | None = None
    # "Follow this story?" (PLAN.md §10.2 D5b): {prompt, other_match}; the viewer sets the follow up themselves.
    follow_offer: dict | None = None
