"""Provider-independent event contract. Adapters own vendor key mappings.

It is the `event` of MatchEvent v2 (local/contracts/README.md §2): strict, extra fields forbidden.
"""
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

EventType = Literal["pass", "shot", "goal", "corner", "card", "save", "tackle",
                    "clearance", "interception", "foul", "touch", "throw_in",
                    "free_kick", "goal_kick", "kick_off", "penalty", "offside",
                    "foul_won", "keeper_claim", "period_start", "period_end",
                    # Opta-style v3 derived events (data-generation/contracts/README.md).
                    "dispossessed", "blocked_pass", "aerial", "take_on", "challenge",
                    "ball_recovery", "out", "corner_awarded", "keeper_pickup", "punch",
                    "offside_provoked", "error", "ball_touch"]
# sourceShotEventId is retained for v2 recordings.
QualifierType = Literal[
    "bodyPart", "distanceMetres", "restart", "score", "relatedEventId", "sourceShotEventId",
    "endX", "endY", "angle", "longBall", "cross", "chipped", "switchOfPlay", "offsidePass",
    "situation", "assistEventId", "bigChance", "goalMouthY", "goalMouthZ", "shotOutcome", "woodwork",
    "saveType", "defensiveBlock", "penaltyAwarded", "ownGoal", "cardReason", "leadsTo", "fromShotOffTarget"]
QualifierValue = bool | int | Annotated[float, Field(allow_inf_nan=False)] | Annotated[str, Field(max_length=120)]
# Opta 0-100 for the acting team; simulated tracking can overshoot a line slightly.
Coordinate = Annotated[float, Field(ge=-10, le=110, allow_inf_nan=False)]
MAX_MATCH_EVENTS = 100_000  # Per match; a GRF match has about 14,000.
_DELIVERY_FIELDS = {"sequence", "video_seconds"}
# Optional v3 context. Snapshot identities exclude it, as ETL does, so a producer
# that omits it still names the same observed prefix.
DETAIL_FIELDS = frozenset({"sequence", "video_seconds", "x", "y", "possession_id", "qualifiers"})


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
    # Broadcast football clock, not wall time. Stoppage repeats clock values across
    # periods, so order by (period, match_time_seconds) or by sequence, never seconds alone.
    match_time_seconds: int = Field(ge=0, le=12000)
    outcome: str | None = Field(default=None, min_length=1, max_length=40)
    distance_metres: float | None = Field(default=None, ge=0, le=200, allow_inf_nan=False)
    deleted: bool = False
    # Optional v3 context. Older recordings and upstream rows may omit it.
    sequence: int | None = Field(default=None, ge=1)
    video_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False,
                                        validation_alias=AliasChoices("video_seconds", "videoSeconds"))
    x: Coordinate | None = None
    y: Coordinate | None = None
    possession_id: int | None = Field(default=None, ge=0,
                                      validation_alias=AliasChoices("possession_id", "possessionId"))
    qualifiers: dict[QualifierType, QualifierValue] = Field(default_factory=dict, max_length=40)

    def same_content(self, other: "Event") -> bool:
        """A redelivered revision may arrive at another sequence/video time."""
        return self.model_dump(exclude=_DELIVERY_FIELDS) == other.model_dump(exclude=_DELIVERY_FIELDS)


_STOPPAGE_AFTER = {1: 45, 2: 90, 3: 105, 4: 120}


def minute_label(period, match_time_seconds):
    """The broadcast minute a viewer reads: 51:18 is the 52nd minute (52′); first-half
    stoppage 45:30 is 45+1′. Every label shown to viewers or models uses this one rule."""
    minute, end = match_time_seconds // 60 + 1, _STOPPAGE_AFTER.get(period, 120)
    return f"{end}+{minute - end}′" if minute > end else f"{minute}′"
