"""Messages this service reads from Event Hubs `match-events` (local/contracts/README.md §2, ETL contracts)."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.models.events import Event

MatchId = Annotated[str, Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')]


class MatchEventV2(BaseModel):
    """One canonical event; `seq` counts 1, 2, 3… per match in send order."""
    model_config = ConfigDict(extra='ignore')
    type: Literal['MatchEvent']
    version: Literal[2]
    matchId: MatchId
    seq: int = Field(ge=1)
    timeStamp: datetime | None = None
    synthetic: bool = True
    event: Event

    @model_validator(mode='after')
    def same_match(self):
        if self.event.match_id != self.matchId or self.event.sequence != self.seq:
            raise ValueError('event.match_id and event.sequence must equal matchId and seq')
        return self


class MatchInfo(BaseModel):
    """MA1: the first message of a match. Only identity is kept here; teams, players and
    capabilities are read from ETL GraphQL (its `matches` read model)."""
    model_config = ConfigDict(extra='ignore')
    feed: Literal['MA1']
    matchId: MatchId
    fixture: str = Field(pattern=r'^[a-z0-9-]{1,55}$')
    sourceMatchId: str | None = Field(default=None, max_length=64)
    runId: str | None = Field(default=None, max_length=64)
    provenance: str | None = Field(default=None, max_length=2000)
    timeStamp: datetime
