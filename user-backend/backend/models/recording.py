"""Metadata contract for a synthetic match recording; event mapping is separate."""
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .rules import Rule

MAX_RECORDING_BYTES = 16 * 1024 * 1024
MAX_RECORDING_EVENTS = 100_000


class Team(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)


class Player(Team):
    team_id: str


class Preset(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    rule: Rule


class Playback(BaseModel):
    duration_seconds: float = Field(gt=0, le=14400, allow_inf_nan=False)
    football_duration_seconds: int = Field(gt=0, le=12000)
    halftime_seconds: float = Field(gt=0, le=7200, allow_inf_nan=False)


class Recording(BaseModel):
    model_config = ConfigDict(strict=True)
    synthetic: bool
    match_id: str = Field(min_length=1, max_length=120)
    teams: list[Team] = Field(min_length=2, max_length=2)
    players: list[Player] = Field(max_length=1000)
    events: list[dict] = Field(min_length=1, max_length=MAX_RECORDING_EVENTS)
    presets: list[Preset] = Field(default_factory=list, max_length=200)
    playback: Playback | None = None

    @model_validator(mode="after")
    def valid_catalogue(self):
        if not self.synthetic:
            raise ValueError("This development adapter accepts synthetic recordings only")
        for rows in (self.teams, self.players, self.presets):
            if len({row.id for row in rows}) != len(rows):
                raise ValueError("Recording catalogue IDs must be unique")
        teams = {team.id for team in self.teams}
        if any(player.team_id not in teams for player in self.players):
            raise ValueError("Every player must belong to a listed team")
        if any(preset.rule.match_id != self.match_id for preset in self.presets):
            raise ValueError("Preset rules must belong to the recording's match")
        return self
