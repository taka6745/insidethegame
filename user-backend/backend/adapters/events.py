"""Swappable event boundary. This adapter reads OUR synthetic Opta-inspired feed.

It is not a licensed Opta schema implementation. No vendor numeric codes are
assumed. Real feed mappings belong in another implementation of EventAdapter.
"""
from typing import Protocol
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.models.events import Event, EventType


class EventAdapter(Protocol):
    def adapt(self, payload: dict) -> Event: ...
    def data_reference(self) -> dict: ...


class _Qualifier(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: str
    value: str | int | float


class _RawEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    eventId: str
    matchId: str
    revision: int = Field(default=1, ge=1)
    sequence: int = Field(ge=1)
    typeName: EventType
    teamId: str | None = None
    playerId: str | None = None
    periodId: int = Field(ge=1, le=5)
    timeMin: int = Field(ge=0, le=200)
    timeSec: int = Field(ge=0, le=59)
    outcome: str | None = None
    qualifiers: list[_Qualifier] = Field(default_factory=list, max_length=32)
    deleted: bool = False
    synthetic: bool = True
    keyMoment: str | None = None
    videoSeconds: float | None = Field(default=None, ge=0, le=14400, allow_inf_nan=False)
    rawTelemetry: dict | None = None

    @field_validator("synthetic")
    @classmethod
    def fixture_only(cls, value):
        if value is not True:
            raise ValueError("Use a production adapter for a non-synthetic feed")
        return value

    @model_validator(mode="after")
    def unique_qualifiers(self):
        keys = [q.type for q in self.qualifiers]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate qualifier keys are ambiguous")
        return self


class OptaInspiredAdapter:
    """Explicit field mapping. Unknown named qualifiers are preserved upstream,
    but have no DSL meaning here; replacing this class does not change the engine.
    Clock minutes already include the period offset (second half starts at 45).
    Restart semantics belong to the recording's versioned data reference.
    """
    def data_reference(self) -> dict:
        from .feed_reference import FeedReference
        return FeedReference.load(Path(__file__).parent / "feed_profiles/opta-inspired-v1.json").describe()

    def adapt(self, payload: dict) -> Event:
        raw = _RawEvent.model_validate(payload)
        qualifiers = {q.type: q.value for q in raw.qualifiers}
        return Event(
            event_id=raw.eventId, match_id=raw.matchId, revision=raw.revision,
            event_type=raw.typeName, team_id=raw.teamId, player_id=raw.playerId,
            body_part=qualifiers.get("bodyPart"), period=raw.periodId,
            match_time_seconds=raw.timeMin * 60 + raw.timeSec,
            outcome=raw.outcome, distance_metres=qualifiers.get("distanceMetres"),
            deleted=raw.deleted,
        )
