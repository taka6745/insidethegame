"""Semantic targets stay separate from generated implementation rules."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.models.rules import Rule
from backend.models.events import EventType


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    description: str = Field(min_length=1, max_length=500)
    operation: Literal["count", "sum"] = "count"
    event_types: tuple[EventType, ...] = ()
    team_ids: tuple[str, ...] = ()
    player_ids: tuple[str, ...] = ()
    body_part: Literal["head", "left_foot", "right_foot", "foot", "other", "hand"] | None = None
    period: int | None = Field(default=None, ge=1, le=5)
    outcome: Literal["success", "failure", "saved", "off_target", "blocked", "red", "yellow"] | None = None
    after_seconds: float | None = Field(default=None, ge=0, le=12000)
    from_seconds: float | None = Field(default=None, ge=0, le=12000)
    before_seconds: float | None = Field(default=None, ge=0, le=12000)
    through_seconds: float | None = Field(default=None, ge=0, le=12000)
    sum_field: Literal["distance_metres"] | None = None

    @model_validator(mode="after")
    def supported(self):
        allowed = {"pass", "shot", "goal", "corner", "card", "save", "tackle", "clearance",
                   "interception", "foul", "touch"}
        if not set(self.event_types) <= allowed:
            raise ValueError("Unsupported event category")
        if self.after_seconds is not None and self.from_seconds is not None:
            raise ValueError("Choose an inclusive or exclusive lower bound")
        if self.before_seconds is not None and self.through_seconds is not None:
            raise ValueError("Choose an inclusive or exclusive upper bound")
        lower = self.after_seconds if self.after_seconds is not None else self.from_seconds
        upper = self.before_seconds if self.before_seconds is not None else self.through_seconds
        if lower is not None and upper is not None and lower >= upper:
            raise ValueError("Time window must have positive duration")
        if (self.operation == "sum") != (self.sum_field is not None):
            raise ValueError("Sum requires distance_metres; count forbids sum_field")
        return self

    def target_rule(self, match_id: str) -> Rule:
        terms = []
        for field, values in (("event_type", self.event_types), ("team_id", self.team_ids),
                              ("player_id", self.player_ids)):
            if values:
                terms.append({"field": field, "op": "in", "value": list(values)})
        for field in ("body_part", "period", "outcome"):
            value = getattr(self, field)
            if value is not None:
                terms.append({"field": field, "op": "eq", "value": value})
        for field, op in (("after_seconds", "gt"), ("from_seconds", "gte"),
                          ("before_seconds", "lt"), ("through_seconds", "lte")):
            value = getattr(self, field)
            if value is not None:
                terms.append({"field": "match_time_seconds", "op": op, "value": value})
        return Rule(match_id=match_id, operation=self.operation, predicates=terms, sum_field=self.sum_field)


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)
    options: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=5)
    missing_fields: list[Literal["player", "team", "metric", "time_window"]] = Field(default_factory=list)


class GoalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["custom", "reuse", "clarification", "unsupported"]
    goal: Goal | None = None
    clarification: Clarification | None = None
    standard_stat_id: str | None = None
    message: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def complete(self):
        if self.status == "custom" and self.goal is None:
            raise ValueError("A custom calculation needs a goal")
        if self.status == "reuse" and not self.standard_stat_id:
            raise ValueError("Reuse requires an existing stat ID")
        if self.status == "clarification":
            if self.clarification is None:
                self.clarification = Clarification(question=self.message or "Which statistic would you like to track?")
            self.message = self.clarification.question
        return self


class PlanOutcome(BaseModel):
    status: Literal["ready", "reuse", "clarification", "unsupported", "failed"]
    source: Literal["fixture", "local"]
    goal: Goal | None = None
    rule: Rule | None = None
    clarification: Clarification | None = None
    standard_stat_id: str | None = None
    attempts: int = 0
    message: str = ""
    model_calls: int | None = None
    stage_seconds: dict[str, float] = Field(default_factory=dict)
