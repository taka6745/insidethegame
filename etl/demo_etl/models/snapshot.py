"""Versioned read watermark shared with consumers; no database concerns."""
import hashlib
import json
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


EventType = Literal[
    'pass', 'shot', 'goal', 'corner', 'card', 'save', 'tackle', 'clearance', 'interception', 'foul', 'touch',
    'throw_in', 'free_kick', 'goal_kick', 'kick_off', 'penalty', 'offside', 'foul_won', 'keeper_claim',
    'period_start', 'period_end',
    # Opta-style v3 derived events (data-generation/docs/opta-events.md).
    'dispossessed', 'blocked_pass', 'aerial', 'take_on', 'challenge', 'ball_recovery', 'out', 'corner_awarded',
    'keeper_pickup', 'punch', 'offside_provoked', 'error', 'ball_touch']
# sourceShotEventId is retained for v2 recordings.
QualifierType = Literal[
    'bodyPart', 'distanceMetres', 'restart', 'score', 'relatedEventId', 'sourceShotEventId',
    'endX', 'endY', 'angle', 'longBall', 'cross', 'chipped', 'switchOfPlay', 'offsidePass',
    'situation', 'assistEventId', 'bigChance', 'goalMouthY', 'goalMouthZ', 'shotOutcome', 'woodwork',
    'saveType', 'defensiveBlock', 'penaltyAwarded', 'cardReason', 'leadsTo', 'fromShotOffTarget']
QualifierValue = bool | int | Annotated[float, Field(allow_inf_nan=False)] | Annotated[str, Field(max_length=120)]
# Opta 0-100 for the acting team; simulated tracking can overshoot a line slightly.
Coordinate = Annotated[float, Field(ge=-10, le=110, allow_inf_nan=False)]


# v3 detail derived from the recording (pinned by recording_hash). Kept out of snapshot IDs and the
# /demo/snapshots body so v2 producers and the narrative stub compute the same digest.
DETAIL_FIELDS = frozenset({'sequence', 'video_seconds', 'x', 'y', 'possession_id', 'qualifiers'})


class Event(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    event_id: str = Field(min_length=1, max_length=120)
    match_id: str = Field(min_length=1, max_length=120)
    revision: int = Field(default=1, ge=1)
    event_type: EventType
    team_id: str | None = None
    player_id: str | None = None
    body_part: Literal['head','left_foot','right_foot','foot','other','hand'] | None = None
    # Broadcast clock: stoppage time repeats clock values, so order by (period, time) or delivery.
    period: int = Field(default=1, ge=1, le=5)
    match_time_seconds: int = Field(ge=0, le=12000)
    outcome: str | None = None
    distance_metres: float | None = Field(default=None, ge=0, le=200, allow_inf_nan=False)
    deleted: bool = False
    sequence: int | None = Field(default=None, ge=1)
    video_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    x: Coordinate | None = None
    y: Coordinate | None = None
    possession_id: int | None = Field(default=None, ge=0)
    qualifiers: dict[QualifierType, QualifierValue] = Field(default_factory=dict, max_length=40)


class Watermark(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    run_id: str
    match_id: str
    recording_hash: str
    cursor: int = Field(ge=0, le=100000)
    clock_seconds: int | None = None
    period: int | None = None
    captured_at: str


class SnapshotInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot: Watermark
    events: list[Event] = Field(default_factory=list, max_length=100000)
    teams: list[dict] = Field(min_length=2, max_length=2)
    players: list[dict] = Field(max_length=1000)
    data_reference: dict

    def identity_dump(self):
        return self.model_dump(mode='json', exclude={'events': {'__all__': set(DETAIL_FIELDS)}})

    def digest(self):
        data = self.identity_dump()
        data['snapshot'].pop('id')
        data['snapshot'].pop('captured_at')
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def validate_identity(self):
        if self.snapshot.cursor != len(self.events) or any(e.match_id != self.snapshot.match_id for e in self.events):
            raise ValueError('Snapshot deliveries do not match its watermark')
        if self.digest() != self.snapshot.id:
            raise ValueError('Snapshot content does not match its ID')
        teams = {t['id'] for t in self.teams}
        players = {p['id'] for p in self.players}
        if len(teams) != 2 or len(players) != len(self.players):
            raise ValueError('Duplicate catalogue IDs')
        if any(e.team_id is not None and e.team_id not in teams or e.player_id is not None and e.player_id not in players for e in self.events):
            raise ValueError('Unknown event participant')
