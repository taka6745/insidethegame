"""Test double: synthetic recordings' canonical keys → `Event`, for tests and benchmarks only (the runtime
receives MatchEvent v2 via adapters/match_stream.py). Not a licensed Opta schema; no vendor numeric codes."""
from typing import get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.models.events import Coordinate, Event, EventType, QualifierType, QualifierValue


_KNOWN_QUALIFIERS = frozenset(get_args(QualifierType))


class _Qualifier(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: str = Field(min_length=1, max_length=60)
    value: QualifierValue


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
    x: Coordinate | None = None
    y: Coordinate | None = None
    possessionId: int | None = Field(default=None, ge=0)
    qualifiers: list[_Qualifier] = Field(default_factory=list, max_length=40)
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
    """Explicit field mapping. Known qualifiers stay available to services; unknown
    named qualifiers stay upstream. Neither has DSL meaning; replacing this class does
    not change the engine. Clock minutes already include the period offset (second half
    starts at 45) and first-half stoppage keeps period 1. Restart semantics belong to
    the recording's versioned data reference.
    """
    def adapt(self, payload: dict) -> Event:
        raw = _RawEvent.model_validate(payload)
        qualifiers = {q.type: q.value for q in raw.qualifiers}
        return Event(
            event_id=raw.eventId, match_id=raw.matchId, revision=raw.revision,
            event_type=raw.typeName, team_id=raw.teamId, player_id=raw.playerId,
            body_part=qualifiers.get("bodyPart"), period=raw.periodId,
            match_time_seconds=raw.timeMin * 60 + raw.timeSec,
            outcome=raw.outcome, distance_metres=qualifiers.get("distanceMetres"),
            deleted=raw.deleted, sequence=raw.sequence, video_seconds=raw.videoSeconds,
            x=raw.x, y=raw.y, possession_id=raw.possessionId,
            qualifiers={k: v for k, v in qualifiers.items() if k in _KNOWN_QUALIFIERS},
        )
