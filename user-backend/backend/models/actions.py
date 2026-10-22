"""SPADL actions as ETL GraphQL serves them (entity spadlActions, etl/contracts/spadl-action.schema.json).

Enums come from backend/contracts/spadl-reference.json, generated from that schema. Coordinates are
team-relative here: the acting team attacks towards x = 105 and y = 0 is its right touchline (the
adapter un-mirrors SPADL's standard frame), so one filter means the same for both teams."""
import json
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SPADL = json.loads((Path(__file__).resolve().parents[1] / 'contracts' / 'spadl-reference.json').read_text())
ACTION_TYPES, RESULTS, BODYPARTS, ZONES = (tuple(SPADL[k]) for k in ('types', 'results', 'bodyparts', 'zones'))
PASS_FAMILY, SHOT_FAMILY = tuple(SPADL['families']['pass']), tuple(SPADL['families']['shot'])
FIELD_LENGTH, FIELD_WIDTH = 105.0, 68.0
GOAL_LINE_TYPE = 15  # Opta "attempt saved": on target when its end reaches the goal line (ETL's shots_on_target).

ActionType = Literal[ACTION_TYPES]
Result = Literal[RESULTS]
Bodypart = Literal[BODYPARTS]
Zone = Literal[ZONES]
# Derived from result, the Opta source type and the end location, exactly as ETL's catalogue counts.
ShotOutcome = Literal['goal', 'saved', 'blocked', 'post', 'off_target']
# keeper_save only: a real save (ETL's shots_saved), a touch of a shot going wide, or an outfield block.
SaveKind = Literal['save', 'wide_touch', 'block']
X = Annotated[float, Field(ge=0, le=FIELD_LENGTH, allow_inf_nan=False)]
Y = Annotated[float, Field(ge=0, le=FIELD_WIDTH, allow_inf_nan=False)]
MAX_MATCH_ACTIONS = 20_000  # Per match; a GRF match has about 3,000.


class SpadlAction(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    match_id: str = Field(min_length=1, max_length=120)
    action_id: int = Field(ge=0)
    period: int = Field(ge=1, le=5)
    # Broadcast clock in whole seconds (ETL clockSeconds, floored: an inserted dribble sits midway between
    # its neighbours): period 2 starts at 2700 and stoppage stays in its period, as Opta timeMin/timeSec.
    match_time_seconds: int = Field(ge=0, le=12000)
    team_id: str = Field(min_length=1, max_length=120)
    player_id: str | None = Field(default=None, min_length=1, max_length=120)
    action_type: ActionType
    result: Result
    bodypart: Bodypart
    bodypart_observed: bool = False
    start_x: X
    start_y: Y
    end_x: X
    end_y: Y
    start_zone: Zone
    end_zone: Zone
    seq: int = Field(ge=1)
    final_seq: int = Field(ge=1)
    source_event_id: str | None = Field(default=None, max_length=120)
    source_type_id: int | None = None
    video_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    possession_id: int | None = Field(default=None, ge=0)
    from_shot_off_target: bool = False
    defensive_block: bool = False

    @property
    def id(self):
        """Evidence identity of this action."""
        return f'a{self.action_id}'

    @property
    def distance_metres(self):
        """Ball travel from start to end location."""
        return math.hypot(self.end_x - self.start_x, self.end_y - self.start_y)

    @property
    def shot_outcome(self):
        if self.action_type not in SHOT_FAMILY:
            return None
        if self.result == 'success':
            return 'goal'
        if self.source_type_id == GOAL_LINE_TYPE:
            return 'saved' if self.end_x >= FIELD_LENGTH else 'blocked'
        return 'post' if self.source_type_id == 14 else 'off_target'

    @property
    def save_kind(self):
        if self.action_type != 'keeper_save':
            return None
        return 'block' if self.defensive_block else 'wide_touch' if self.from_shot_off_target else 'save'

    @classmethod
    def from_row(cls, row, match_id, home_team_id):
        """One DAB spadlActions item (camelCase, SPADL standard frame) → team-relative action."""
        home = row['teamId'] == home_team_id
        rx = (lambda v: v) if home else (lambda v: FIELD_LENGTH - v)
        ry = (lambda v: v) if home else (lambda v: FIELD_WIDTH - v)
        return cls(match_id=match_id, action_id=row['actionId'], period=row['periodId'],
                   match_time_seconds=math.floor(row['clockSeconds']), team_id=row['teamId'], player_id=row.get('playerId'),
                   action_type=row['typeName'], result=row['resultName'], bodypart=row['bodypartName'],
                   bodypart_observed=bool(row.get('bodypartObserved')),
                   start_x=rx(row['startX']), start_y=ry(row['startY']), end_x=rx(row['endX']), end_y=ry(row['endY']),
                   start_zone=row['startZone'], end_zone=row['endZone'], seq=row['seq'], final_seq=row['finalSeq'],
                   source_event_id=row.get('sourceEventId'), source_type_id=row.get('sourceTypeId'),
                   video_seconds=row.get('videoSeconds'), possession_id=row.get('possessionId'),
                   from_shot_off_target=bool(row.get('fromShotOffTarget')), defensive_block=bool(row.get('defensiveBlock')))

    def row(self):
        """The JSON shape tools and caches use (with derived fields)."""
        return {**self.model_dump(mode='json'), 'id': self.id, 'shot_outcome': self.shot_outcome,
                'save_kind': self.save_kind, 'distance_metres': round(self.distance_metres, 1)}
