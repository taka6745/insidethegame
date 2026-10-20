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


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    match_id: str = Field(min_length=1, max_length=120)
    operation: Literal["count", "sum"] = "count"
    predicates: tuple[Predicate, ...] = Field(default=(), max_length=16)
    sum_field: Literal["distance_metres"] | None = None

    @model_validator(mode="after")
    def aggregation(self):
        if (self.operation == "sum") != (self.sum_field is not None):
            raise ValueError("Sum requires sum_field; count cannot have one")
        return self

    @property
    def calculation_id(self) -> str:
        terms = sorted({json.dumps(p.canonical(), sort_keys=True, separators=(",", ":")) for p in self.predicates})
        identity = json.dumps([self.match_id, self.operation, self.sum_field, terms], separators=(",", ":"))
        return "calc_" + hashlib.sha256(identity.encode()).hexdigest()

    def matches(self, event: Event) -> bool:
        return not event.deleted and event.match_id == self.match_id and all(p.matches(event) for p in self.predicates)

    def contribution(self, event: Event | None) -> float:
        if event is None or not self.matches(event):
            return 0
        return 1 if self.operation == "count" else (getattr(event, self.sum_field) or 0)


FilterRule = Rule
