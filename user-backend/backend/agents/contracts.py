"""Prompt and strict wire contracts generated from the typed domain models."""
from copy import deepcopy
from functools import lru_cache
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, create_model
from pydantic_core import PydanticUndefined

from backend.agents.models import LocationBound, AggregateGoal, Clarification, Goal, GoalDecision


def decision_contract() -> dict:
    schema = GoalDecision.model_json_schema()
    definitions = schema.get("$defs", {})

    def inline(value):
        if isinstance(value, list):
            return [inline(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return inline(definitions[value["$ref"].rsplit("/", 1)[-1]])
        return {key: inline(item) for key, item in value.items()
                if key not in {"$defs", "title", "default"}}

    return inline(schema)


# Wire decisions make status-dependent requirements visible to the provider.
# Goal and Clarification remain the source of field types and local validation.
class _WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ReuseDecision(_WireModel):
    status: Literal["reuse"]
    standard_stat_id: str = Field(min_length=1)


class _UnsupportedDecision(_WireModel):
    status: Literal["unsupported"]
    message: str = Field(min_length=1, max_length=1000)


def _required_model(source: type[BaseModel]) -> type[BaseModel]:
    """Retain source validators/types while requiring its defaulted wire fields."""
    def contains_model(annotation):
        return ((isinstance(annotation, type) and issubclass(annotation, BaseModel))
                or any(contains_model(item) for item in get_args(annotation)))

    fields = {}
    for name, original in source.model_fields.items():
        # Tightening nested JSON Schema without changing its validator can silently
        # fill missing fields or drop extras. Require an explicit wire adapter first.
        annotation = original.annotation
        if name == "inputs" and issubclass(source, Goal):
            annotation = tuple[_required_model(AggregateGoal), ...]
        elif name == "locations" and issubclass(source, AggregateGoal):
            annotation = tuple[_required_model(LocationBound), ...]
        elif contains_model(original.annotation):
            raise ValueError("Nested model fields require an explicit strict wire adapter")
        field = deepcopy(original)
        field.default = PydanticUndefined
        field.default_factory = None
        fields[name] = (annotation, field)
    return create_model(f"{source.__name__}Wire", __base__=source, **fields)


@lru_cache(maxsize=16)
def decision_envelope_model(goal_type: type[Goal] = Goal) -> type[BaseModel]:
    """Typed root object with four exclusive status shapes and existing validators."""
    if not isinstance(goal_type, type) or not issubclass(goal_type, Goal):
        raise TypeError("goal_type must be Goal or a Goal subclass")
    custom = create_model("CustomDecision", __base__=_WireModel,
                          status=(Literal["custom"], ...), goal=(_required_model(goal_type), ...))
    clarification = create_model("_ClarificationDecision", __base__=_WireModel,
                                 status=(Literal["clarification"], ...),
                                 clarification=(_required_model(Clarification), ...))
    return create_model("DecisionEnvelope", __base__=_WireModel,
                        decision=(custom | clarification | _ReuseDecision | _UnsupportedDecision, ...))


def strict_decision_contract(goal_type: type[Goal] = Goal) -> dict:
    """Require provider output fields without making non-nullable defaults nullable.

    Providers implementing strict structured output require every object property
    to appear. A defaulted array therefore remains an array (use []), while an
    originally nullable scalar may be null. Local Pydantic validation still owns
    semantic cross-field checks such as a positive-duration time window.
    """
    schema = decision_envelope_model(goal_type).model_json_schema()

    def strict(value):
        if isinstance(value, list):
            return [strict(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: strict(item) for key, item in value.items() if key != "default"}
        if result.get("type") == "object":
            # Do not silently turn a future arbitrary-key map into an empty object.
            if result.get("additionalProperties") not in (None, False):
                raise ValueError("Strict decision contracts require explicit object properties")
            result["additionalProperties"] = False
            result["required"] = list(result.get("properties", {}))
        return result

    return strict(schema)
