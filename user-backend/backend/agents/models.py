"""Semantic targets stay separate from generated implementation rules."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.models.rules import Rule
from backend.models.clarifications import FollowUpQuestion
from backend.models.events import EventType


class AggregateGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    description: str = Field(min_length=1, max_length=500)
    operation: Literal["count", "sum", "average"] = "count"
    event_types: tuple[EventType, ...] = Field(default=(), description="Event categories to include. Empty means all categories. Use the feed contract to avoid overlapping action records.")
    team_ids: tuple[str, ...] = Field(default=(), description="Explicitly requested teams. Empty means all teams. Never infer a team from a named player.")
    player_ids: tuple[str, ...] = Field(default=(), description="Explicitly requested players from the match catalogue. Empty means all players.")
    outcomes: tuple[Literal["success", "failure", "saved", "off_target", "post", "blocked", "red", "yellow", "second_yellow"], ...] = ()
    coverage: Literal["complete", "recorded"] = Field(default="complete", description="Recorded counts include only classified records in a feed-declared event group; they do not claim exhaustive physical coverage. Label them Recorded. Complete requires full field coverage.")
    body_part: Literal["head", "left_foot", "right_foot", "foot", "other", "hand"] | None = None
    period: int | None = Field(default=None, ge=1, le=5, description="Null means the whole match. Select a period only if requested: 1 first half, 2 second half. A minute bound does not imply a period.")
    outcome: Literal["success", "failure", "saved", "off_target", "post", "blocked", "red", "yellow", "second_yellow"] | None = None
    after_seconds: float | None = Field(default=None, ge=0, le=12000, description="Exclusive lower bound in whole-match seconds; null means none. Convert bare match minutes to seconds.")
    from_seconds: float | None = Field(default=None, ge=0, le=12000, description="Inclusive lower bound in whole-match seconds; null means none. Convert bare match minutes to seconds.")
    before_seconds: float | None = Field(default=None, ge=0, le=12000, description="Exclusive upper bound in whole-match seconds; null means none. Convert bare match minutes to seconds.")
    through_seconds: float | None = Field(default=None, ge=0, le=12000, description="Inclusive upper bound in whole-match seconds; null means none. Convert bare match minutes to seconds.")
    sum_field: Literal["distance_metres"] | None = None

    @model_validator(mode="after")
    def supported(self):
        if self.after_seconds is not None and self.from_seconds is not None:
            raise ValueError("Choose an inclusive or exclusive lower bound")
        if self.before_seconds is not None and self.through_seconds is not None:
            raise ValueError("Choose an inclusive or exclusive upper bound")
        lower = self.after_seconds if self.after_seconds is not None else self.from_seconds
        upper = self.before_seconds if self.before_seconds is not None else self.through_seconds
        if lower is not None and upper is not None and lower >= upper:
            raise ValueError("Time window must have positive duration")
        if self.operation in {"percentage", "ratio", "difference"}:
            return self
        if self.coverage == 'recorded' and (self.operation != 'count' or self.body_part is None):
            raise ValueError('Recorded coverage requires a body-part count')
        if self.outcome is not None and self.outcomes:
            raise ValueError("Choose outcome or outcomes, not both")
        if (self.operation in {"sum", "average"}) != (self.sum_field is not None):
            raise ValueError("Sum requires distance_metres; count forbids sum_field")
        return self

    def target_rule(self, match_id: str) -> Rule:
        if self.operation == "average":
            values = self.model_dump(exclude={"operation", "inputs"})
            total = AggregateGoal(**values, operation="sum").target_rule(match_id)
            present = total.model_copy(update={"operation": "count_present"})
            return Rule(match_id=match_id, operation="average", inputs=(total, present))
        terms = []
        for field, values in (("event_type", self.event_types), ("team_id", self.team_ids),
                              ("player_id", self.player_ids)):
            if values:
                terms.append({"field": field, "op": "in", "value": list(values)})
        if self.outcomes:
            terms.append({"field": "outcome", "op": "in", "value": self.outcomes})
        for field in ("body_part", "period", "outcome"):
            value = getattr(self, field)
            if value is not None:
                terms.append({"field": field, "op": "eq", "value": value})
        for field, op in (("after_seconds", "gt"), ("from_seconds", "gte"),
                          ("before_seconds", "lt"), ("through_seconds", "lte")):
            value = getattr(self, field)
            if value is not None:
                terms.append({"field": "match_time_seconds", "op": op, "value": value})
        return Rule(match_id=match_id, operation=self.operation, predicates=terms, sum_field=self.sum_field, coverage=self.coverage)


class Goal(AggregateGoal):
    operation: Literal["count", "sum", "average", "percentage", "ratio", "difference"] = "count"
    inputs: tuple[AggregateGoal, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def composite_goal(self):
        composite = self.operation in {'percentage', 'ratio', 'difference'}
        if not composite:
            if self.inputs:
                raise ValueError("Simple goals cannot contain inputs")
            return self
        if len(self.inputs) != 2 or any(item.operation == 'average' for item in self.inputs):
            raise ValueError("Composite goals need exactly two count or sum inputs")
        scope = self.model_dump(exclude={'description', 'operation', 'inputs', 'coverage'})
        if self.coverage != 'complete' or any(value not in (None, (), []) for value in scope.values()):
            raise ValueError("Put all composite constraints in each input, not on the formula")
        return self

    def target_rule(self, match_id: str) -> Rule:
        if self.operation in {'percentage', 'ratio', 'difference'}:
            return Rule(match_id=match_id, operation=self.operation,
                        inputs=tuple(item.target_rule(match_id) for item in self.inputs))
        return super().target_rule(match_id)


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class Clarification(FollowUpQuestion):
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
    goal_failure_reasons: list[str] | None = None
    goal_validation_errors: list[dict] | None = None
    stage_seconds: dict[str, float] = Field(default_factory=dict)
