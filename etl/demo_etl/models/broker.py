"""Versioned broker contract for the recorded-match demo."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from demo_etl.models.snapshot import Event, SnapshotInput


class MatchEventMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['MatchEvent']
    version: Literal[1]
    snapshot: SnapshotInput
    event: Event | None

    @model_validator(mode='after')
    def metadata_only(self):
        if self.snapshot.events:
            raise ValueError('Broker snapshots contain metadata only')
        return self
