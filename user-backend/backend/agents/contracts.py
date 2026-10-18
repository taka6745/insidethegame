"""Small, inline model-facing schema; Pydantic remains the validation authority."""
from .models import GoalDecision


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
