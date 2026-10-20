"""Bounded deterministic DSL: conjunctions of typed predicates, count or sum."""
import hashlib
import json
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

from .events import Event, EventType

INDEX_FIELDS = ("event_type", "team_id", "player_id", "body_part", "period", "outcome")
NUMERIC_FIELDS = {"period", "match_time_seconds"}


class Predicate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: Literal["event_type", "team_id", "player_id", "body_part", "period",
                   "match_time_seconds", "outcome"]
    op: Literal["eq", "in", "gt", "gte", "lt", "lte"]
    value: str | int | float | tuple[str | int | float, ...]

    @field_validator("value", mode="before")
    @classmethod
    def freeze_value(cls, value):
        values = value if isinstance(value, (list, tuple)) else [value]
        if any(isinstance(item, bool) or not isinstance(item, (str, int, float)) for item in values):
            raise ValueError("Predicate values must be strings or numbers, never booleans")
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def typed_value(self):
        values = self.value if isinstance(self.value, tuple) else (self.value,)
        if (self.op == "in") != isinstance(self.value, tuple):
            raise ValueError("Only 'in' accepts a list")
        if not 1 <= len(values) <= 32:
            raise ValueError("Membership needs between 1 and 32 values")
        numeric = self.field in NUMERIC_FIELDS
        if self.op not in {"eq", "in"} and not numeric:
            raise ValueError("Range comparisons require a numeric field")
        for value in values:
            if numeric:
                if not isinstance(value, (int, float)) or not 0 <= value <= 12000:
                    raise ValueError("Time and period predicates require bounded numbers")
                if self.field == "period" and (value != int(value) or not 1 <= value <= 5):
                    raise ValueError("Period must be 1 to 5")
            elif not isinstance(value, str) or not 1 <= len(value) <= 120:
                raise ValueError("Categorical predicates require nonempty strings")
            if self.field == "event_type" and value not in get_args(EventType):
                raise ValueError("Unknown canonical event type")
            if self.field == "body_part" and value not in {"head", "left_foot", "right_foot", "foot", "other", "hand"}:
                raise ValueError("Unknown canonical body part")
        return self

    def matches(self, event: Event) -> bool:
        actual = getattr(event, self.field)
        if actual is None:
            return False
        if self.op == "eq":
            return actual == self.value
        if self.op == "in":
            return actual in self.value
        if self.op == "gt":
            return actual > self.value
        if self.op == "gte":
            return actual >= self.value
        if self.op == "lt":
            return actual < self.value
        return actual <= self.value

    def canonical(self):
        value = self.value
        if isinstance(value, tuple):
            value = sorted({int(item) if isinstance(item, float) and item.is_integer() else item for item in value})
            if len(value) == 1:
                return {"field": self.field, "op": "eq", "value": value[0]}
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return {"field": self.field, "op": self.op, "value": value}


class AggregateRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    match_id: str = Field(min_length=1, max_length=120)
    operation: Literal["count", "sum", "count_present"] = "count"
    predicates: tuple[Predicate, ...] = Field(default=(), max_length=16)
    sum_field: Literal["distance_metres"] | None = None
    coverage: Literal["complete", "recorded"] = "complete"

    @model_validator(mode="after")
    def aggregation(self):
        if self.operation in {"percentage", "ratio", "difference", "average"}:
            return self
        if (self.operation in {"sum", "count_present"}) != (self.sum_field is not None):
            raise ValueError("Sum requires sum_field; count cannot have one")
        if self.coverage == 'recorded' and (self.operation != 'count' or not any(
                p.field == 'body_part' for p in self.predicates)):
            raise ValueError("Recorded coverage requires a body-part count")
        return self

    @property
    def calculation_id(self) -> str:
        terms = sorted({json.dumps(p.canonical(), sort_keys=True, separators=(",", ":")) for p in self.predicates})
        parts = [self.match_id, self.operation, self.sum_field, terms]
        if self.coverage != 'complete':
            parts.append(self.coverage)  # Preserve existing IDs for complete-coverage rules.
        identity = json.dumps(parts, separators=(",", ":"))
        return "calc_" + hashlib.sha256(identity.encode()).hexdigest()

    def matches(self, event: Event) -> bool:
        return not event.deleted and event.match_id == self.match_id and all(p.matches(event) for p in self.predicates)

    def contribution(self, event: Event | None) -> float:
        if event is None or not self.matches(event):
            return 0
        if self.operation == "count":
            return 1
        value = getattr(event, self.sum_field)
        return int(value is not None) if self.operation == "count_present" else (value or 0)


class Rule(AggregateRule):
    """One formula over two aggregate leaves; never executable model output."""
    operation: Literal["count", "sum", "count_present", "percentage", "ratio", "difference", "average"] = "count"
    inputs: tuple[AggregateRule, ...] = Field(default=(), max_length=2)

    @property
    def composite(self) -> bool:
        return self.operation in {"percentage", "ratio", "difference", "average"}

    @model_validator(mode="after")
    def formula(self):
        if not self.composite:
            if self.inputs:
                raise ValueError("Aggregate leaves cannot contain inputs")
            return self
        if len(self.inputs) != 2 or self.predicates or self.sum_field is not None or self.coverage != 'complete':
            raise ValueError("A formula requires exactly two aggregate inputs and no outer filters")
        left, right = self.inputs
        if any(item.operation not in {"count", "sum", "count_present"} for item in self.inputs):
            raise ValueError("Nested formulas are unsupported")
        if any(item.match_id != self.match_id for item in self.inputs):
            raise ValueError("Formula inputs must belong to the same match")
        units = [item.sum_field if item.operation == 'sum' else 'count' for item in self.inputs]
        if self.operation in {'percentage', 'ratio', 'difference'} and units[0] != units[1]:
            raise ValueError("Percentage, ratio and difference require compatible input units")
        if self.operation == 'percentage' and not _subset(left, right):
            raise ValueError("Percentage numerator must be a subset of its denominator")
        if self.operation == 'average':
            if (left.operation != 'sum' or right.operation != 'count_present'
                    or left.sum_field != right.sum_field or _terms(left) != _terms(right)):
                raise ValueError("Average requires sum and count of present values over identical filters")
        return self

    @property
    def calculation_id(self) -> str:
        if not self.composite:
            return super().calculation_id
        identity = json.dumps(['formula-v1', self.match_id, self.operation,
                               [item.calculation_id for item in self.inputs]], separators=(',', ':'))
        return 'calc_' + hashlib.sha256(identity.encode()).hexdigest()

    @property
    def unit(self) -> str:
        if self.operation == 'percentage':
            return '%'
        if self.operation in {'sum', 'average'}:
            return 'm'
        if self.operation == 'difference' and self.inputs[0].operation == 'sum':
            return 'm'
        return ''


def _terms(rule):
    return {json.dumps(p.canonical(), sort_keys=True) for p in rule.predicates}


def _subset(numerator, denominator):
    # Prove only bounded conjunction containment; never guess unsupported equivalence.
    for predicate in denominator.predicates:
        if json.dumps(predicate.canonical(), sort_keys=True) in _terms(numerator):
            continue
        if predicate.op in {'eq', 'in'}:
            allowed = {predicate.value} if predicate.op == 'eq' else set(predicate.value)
            constrained = [p for p in numerator.predicates if p.field == predicate.field and p.op in {'eq', 'in'}]
            if constrained:
                values = set.intersection(*[{p.value} if p.op == 'eq' else set(p.value) for p in constrained])
                if values <= allowed:
                    continue
        return False
    return (numerator.operation == denominator.operation and numerator.sum_field == denominator.sum_field
            and numerator.coverage == denominator.coverage)


FilterRule = Rule
