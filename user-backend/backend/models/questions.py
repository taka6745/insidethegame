"""Question contracts: snapshots freeze deliveries, not just the football clock."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .events import Event

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
    events: list[Event] = Field(max_length=20000)
    teams: list[dict] = Field(max_length=2)
    players: list[dict] = Field(max_length=1000)
    data_reference: dict

class QuestionDraft(Strict):
    answer_kind: Literal['football', 'match', 'statistic']
    standard_stat_id: str | None = Field(default=None, max_length=200)
    selected_offer_id: str | None = Field(default=None, max_length=100)
    statistic_request: str | None = Field(default=None, min_length=1, max_length=2000)
    status: Literal['answer', 'clarification', 'unsupported']
    text: str = Field(min_length=1, max_length=1800)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)

class QuestionReply(QuestionDraft):
    snapshot: MatchSnapshot
    offers: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    mode: Literal['fixture', 'local']
    goal: dict | None = None
