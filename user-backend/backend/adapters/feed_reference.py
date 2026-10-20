"""Versioned feed meanings paired with the executable canonical event schema."""
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from backend.models.events import Event


class FeedReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_id: str = Field(min_length=1)
    provenance: str
    fields: dict[str, str]
    events: dict[str, str]
    guarantees: list[str]
    unavailable: list[str]

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_text())

    def describe(self, event_model=Event) -> dict:
        schema = event_model.model_json_schema()
        # Inline references so each exported field schema remains self-contained
        # when a future Literal becomes an Enum or another referenced type.
        def compact(value, refs=()):
            if isinstance(value, list):
                return [compact(item, refs) for item in value]
            if isinstance(value, dict):
                if "$ref" in value:
                    ref = value["$ref"]
                    if ref in refs or not ref.startswith("#/$defs/"):
                        raise ValueError("Recursive or external field schemas need explicit reference support")
                    definition = schema["$defs"][ref.removeprefix("#/$defs/")]
                    return compact({**definition, **{k: v for k, v in value.items() if k != "$ref"}}, (*refs, ref))
                return {key: compact(item, refs) for key, item in value.items()
                        if key not in {"title", "default"}}
            return value
        properties = compact(schema["properties"])
        if set(self.fields) != set(properties):
            raise ValueError("Feed reference fields differ from the canonical event schema; review the profile")
        event_schema = properties["event_type"]
        categories = event_schema.get("enum", [event_schema.get("const")])
        if set(self.events) != set(categories):
            raise ValueError("Feed reference event meanings differ from the event enum; review the profile")
        # Types/enums/bounds come from code, never from a second manually copied schema.
        return {
            "contract_id": self.contract_id,
            "schema_sha256": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
            "provenance": self.provenance,
            "fields": {name: {"meaning": meaning, "schema": compact(properties[name])}
                       for name, meaning in self.fields.items()},
            "events": self.events,
            "guarantees": self.guarantees,
            "unavailable": self.unavailable,
        }
