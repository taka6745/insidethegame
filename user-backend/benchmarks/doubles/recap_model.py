"""Neutral recap archive. Children remain readable after compaction."""
from pydantic import BaseModel, Field

class ContextBlock(BaseModel):
    id: str
    match_id: str
    tier: str
    start_seconds: int
    end_seconds: int
    summary: str
    created_seq: int
    child_ids: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    supersession_seq: int | None = None
