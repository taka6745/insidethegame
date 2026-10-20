"""Versioned broker messages; recorded events remain ETL-owned."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .snapshots import Checkpoint, SnapshotInput


class SnapshotReady(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['MatchSnapshotReady']
    version: Literal[1]
    snapshot: SnapshotInput

    @model_validator(mode='after')
    def metadata_only(self):
        if self.snapshot.events:
            raise ValueError('Snapshot notification must contain metadata only')
        timestamp = datetime.fromisoformat(self.snapshot.snapshot.captured_at.replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('Snapshot capture time must include a timezone')
        return self


class BucketNarratives(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['BucketNarratives'] = 'BucketNarratives'
    version: Literal[1] = 1
    snapshot: Checkpoint
    items: list[dict] = Field(max_length=480)
    events: list[dict] = Field(max_length=30)
    audience_revision: str | int | None
