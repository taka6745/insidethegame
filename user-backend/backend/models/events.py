"""Provider-independent event contract. Adapters own vendor key mappings."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal["pass", "shot", "goal", "corner", "card", "save", "tackle",
                    "clearance", "interception", "foul", "touch"]


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: str = Field(min_length=1, max_length=120)
    match_id: str = Field(min_length=1, max_length=120)
    revision: int = Field(default=1, ge=1)
    event_type: EventType
    team_id: str | None = Field(default=None, min_length=1, max_length=120)
    player_id: str | None = Field(default=None, min_length=1, max_length=120)
    body_part: Literal["head", "left_foot", "right_foot", "foot", "other", "hand"] | None = None
    period: int = Field(default=1, ge=1, le=5)
    # Whole-match football clock, not wall time. Period disambiguates stoppage time.
    match_time_seconds: int = Field(ge=0, le=12000)
    outcome: str | None = Field(default=None, min_length=1, max_length=40)
    distance_metres: float | None = Field(default=None, ge=0, le=200, allow_inf_nan=False)
    deleted: bool = False


CanonicalEvent = Event
