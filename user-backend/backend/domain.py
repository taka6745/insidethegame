"""Pure rules shared by the API and tests."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Team = Literal["home", "away", "neutral"]
Style = Literal["analytical", "simple", "casual", "experienced"]
STATS = frozenset({"goals", "cards", "shots", "possession"})


class MatchEvent(BaseModel):
    """Synthetic harness contract; the upstream production schema is still separate."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    match_id: str
    sequence: int = Field(ge=1)
    minute: int = Field(ge=0, le=150)
    team: Literal["home", "away"]
    type: Literal["pass", "shot", "goal", "goal_cancelled", "card", "corner", "save", "tackle"]
    body_part: Literal["foot", "head"] | None = None
    related_event_id: str | None = None
    key_moment: str | None = Field(default=None, max_length=200)


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team: Team
    fan_style: Style

    @property
    def bucket(self):
        return f"{self.team}:{self.fan_style}"


class Narrative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    match_id: str = Field(min_length=1, max_length=100)
    team: Team
    fan_style: Style
    minute: int = Field(ge=0, le=150)
    text: str = Field(min_length=1, max_length=4000)
    stat_ids: list[str] | None = None

    @field_validator("stat_ids")
    @classmethod
    def approved_selection(cls, value):
        if value is not None and (not value or len(value) != len(set(value)) or not set(value) <= STATS):
            raise ValueError("Choose unique stat IDs from the approved pool")
        return value

    @property
    def bucket(self):
        return f"{self.team}:{self.fan_style}"


class RuleError(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def pin(pins, calculation_id, slots, replace=None):
    result = list(pins)
    if calculation_id in result:
        return result
    if replace is not None:
        if replace not in result:
            raise RuleError("pin_not_found", "The replacement must be an existing custom pin", 404)
        result[result.index(replace)] = calculation_id
    elif len(result) < slots:
        result.append(calculation_id)
    else:
        raise RuleError("choose_pin_to_replace", "Every slot is custom; choose a pin to replace")
    return result


def card_ids(defaults, pins, slots):
    if len(defaults) < slots or len(pins) > slots:
        raise RuleError("invalid_selection", "Not enough approved defaults for the configured slots", 422)
    return [("default", key) for key in defaults[:slots - len(pins)]] + [("custom", key) for key in pins]
