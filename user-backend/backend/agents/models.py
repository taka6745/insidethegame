"""Semantic targets stay separate from generated implementation rules."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.models.rules import Rule
from backend.models.clarifications import FollowUpQuestion
from backend.models.actions import ActionType, Bodypart, Result, SaveKind, SHOT_FAMILY, ShotOutcome, Zone


class LocationBound(BaseModel):
    """Team-relative metres: the acting team attacks towards x = 105; y = 0 is its right touchline (pitch 105 x 68)."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: Literal["start_x", "start_y", "end_x", "end_y"]
    gte: float | None = Field(default=None, ge=0, le=105)
    lte: float | None = Field(default=None, ge=0, le=105)

    @model_validator(mode="after")
    def bounded(self):
        if self.gte is None and self.lte is None:
            raise ValueError("A location bound needs gte or lte")
        if self.gte is not None and self.lte is not None and self.gte > self.lte:
            raise ValueError("Location bound gte exceeds lte")
        return self


class AggregateGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    description: str = Field(min_length=1, max_length=500)
    operation: Literal["count", "sum", "average"] = "count"
    action_types: tuple[ActionType, ...] = Field(default=(), description="SPADL action types to include. Empty means all types.")
    team_ids: tuple[str, ...] = Field(default=(), description="Explicitly requested teams. Empty means all teams. Never infer a team from a named player.")
    player_ids: tuple[str, ...] = Field(default=(), description="Explicitly requested players from the match catalogue. Empty means all players.")
    results: tuple[Result, ...] = Field(default=(), description="SPADL results to include. Empty means any result.")
    bodyparts: tuple[Bodypart, ...] = Field(default=(), description="SPADL body parts to include. Empty means any.")
    start_zones: tuple[Zone, ...] = Field(default=(), description="Team-relative zone where the action starts. Empty means anywhere.")
    end_zones: tuple[Zone, ...] = Field(default=(), description="Team-relative zone where the action ends. Empty means anywhere.")
    shot_outcomes: tuple[ShotOutcome, ...] = Field(default=(), description="For shot types only: goal, saved (on target, not scored), blocked, post, off_target.")
    save_kinds: tuple[SaveKind, ...] = Field(default=(), description="For keeper_save only: save (a real goalkeeper save), wide_touch (touched a shot going wide), block (outfield block).")
    locations: tuple[LocationBound, ...] = Field(default=(), max_length=4, description="Optional start/end x/y ranges in team-relative metres.")
    coverage: Literal["complete", "recorded"] = Field(default="complete", description="recorded: count only actions whose body part a provider qualifier named; label it Recorded. Requires bodyparts.")
    period: int | None = Field(default=None, ge=1, le=5, description="Null means the whole match. Select a period only if requested: 1 first half, 2 second half. A minute bound does not imply a period.")
    after_seconds: float | None = Field(default=None, ge=0, le=12000, description="Exclusive lower bound in whole-match seconds; null means none. Convert bare match minutes to seconds.")
    from_seconds: float | None = Field(default=None, ge=0, le=12000, description="Inclusive lower bound in whole-match seconds; null means none. Convert bare match minutes to seconds.")
    before_seconds: float | None = Field(default=None, ge=0, le=12000, description="Exclusive upper bound in whole-match seconds; null means none. Convert bare match minutes to seconds.")
    through_seconds: float | None = Field(default=None, ge=0, le=12000, description="Inclusive upper bound in whole-match seconds; null means none. Convert bare match minutes to seconds.")
    sum_field: Literal["distance_metres"] | None = Field(default=None, description="distance_metres: ball travel from start to end location.")

    @model_validator(mode="after")
    def supported(self):
        if self.coverage == "recorded" and not self.bodyparts and self.operation == "count":
            # "Recorded" qualifies body-part classification only; without a body part it is a complete count.
            object.__setattr__(self, "coverage", "complete")
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
        if self.coverage == 'recorded' and (self.operation != 'count' or not self.bodyparts):
            raise ValueError('Recorded coverage requires a body-part count')
        if (self.operation in {"sum", "average"}) != (self.sum_field is not None):
            raise ValueError("Sum requires distance_metres; count forbids sum_field")
        if self.shot_outcomes and (not self.action_types or not set(self.action_types) <= set(SHOT_FAMILY)):
            raise ValueError("shot_outcomes requires shot action_types only")
        if self.save_kinds and set(self.action_types) != {"keeper_save"}:
            raise ValueError("save_kinds requires action_types [keeper_save] only")
        for bound in self.locations:
            if bound.field.endswith('_y') and any(v is not None and v > 68 for v in (bound.gte, bound.lte)):
                raise ValueError("y bounds are 0 to 68 metres")
        return self

    def target_rule(self, match_id: str) -> Rule:
        if self.operation == "average":
            values = self.model_dump(exclude={"operation", "inputs", "rank_by"})
            total = AggregateGoal(**values, operation="sum").target_rule(match_id)
            present = total.model_copy(update={"operation": "count_present"})
            return Rule(match_id=match_id, operation="average", inputs=(total, present))
        terms = []
        for field, values in (("action_type", self.action_types), ("team_id", self.team_ids),
                              ("player_id", self.player_ids), ("result", self.results), ("bodypart", self.bodyparts),
                              ("start_zone", self.start_zones), ("end_zone", self.end_zones),
                              ("shot_outcome", self.shot_outcomes), ("save_kind", self.save_kinds)):
            if values:
                terms.append({"field": field, "op": "in", "value": list(values)})
        if self.period is not None:
            terms.append({"field": "period", "op": "eq", "value": self.period})
        for field, op in (("after_seconds", "gt"), ("from_seconds", "gte"),
                          ("before_seconds", "lt"), ("through_seconds", "lte")):
            value = getattr(self, field)
            if value is not None:
                terms.append({"field": "match_time_seconds", "op": op, "value": value})
        for bound in self.locations:
            for op in ("gte", "lte"):
                if getattr(bound, op) is not None:
                    terms.append({"field": bound.field, "op": op, "value": getattr(bound, op)})
        return Rule(match_id=match_id, operation=self.operation, predicates=terms, sum_field=self.sum_field, coverage=self.coverage)


class Goal(AggregateGoal):
    operation: Literal["count", "sum", "average", "percentage", "ratio", "difference"] = "count"
    inputs: tuple[AggregateGoal, ...] = Field(default=(), max_length=2)
    rank_by: Literal["player"] | None = Field(default=None, description="player: rank players by this count or sum (who has the most). player_ids, if any, are the only candidates.")

    @model_validator(mode="after")
    def composite_goal(self):
        composite = self.operation in {'percentage', 'ratio', 'difference'}
        if self.rank_by and self.operation not in {'count', 'sum'}:
            raise ValueError("Players can be ranked by a count or sum only")
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
    standard_stat_ids: list[str] = Field(default_factory=list, max_length=6, description="Several catalogue IDs for a multi-part request, or [first, second] for a formula.")
    formula: Literal["percentage", "ratio", "difference"] | None = Field(default=None, description="Combine exactly two catalogue counts: 100*first/second, first/second or first-second.")
    message: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def complete(self):
        if self.status == "custom" and self.goal is None:
            raise ValueError("A custom calculation needs a goal")
        if self.status == "reuse":
            # One ID or several; standard_stat_id stays the first for single-stat consumers.
            self.standard_stat_ids = list(dict.fromkeys(self.standard_stat_ids or [self.standard_stat_id or ""]))
            if not all(self.standard_stat_ids):
                raise ValueError("Reuse requires an existing stat ID")
            self.standard_stat_id = self.standard_stat_ids[0]
            if self.formula and len(self.standard_stat_ids) != 2:
                raise ValueError("A formula combines exactly two catalogue stats")
        elif self.standard_stat_ids or self.formula:
            raise ValueError("Only reuse selects catalogue stats")
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
    standard_stat_ids: list[str] = Field(default_factory=list)
    formula: Literal["percentage", "ratio", "difference"] | None = None
    attempts: int = 0
    message: str = ""
    model_calls: int | None = None
    goal_failure_reasons: list[str] | None = None
    goal_validation_errors: list[dict] | None = None
    stage_seconds: dict[str, float] = Field(default_factory=dict)
