"""Neutral upstream contract and editable, shared audience definitions."""
import hashlib
import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Key = Annotated[str, Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')]
Description = Annotated[str, Field(min_length=1, max_length=600)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudienceOption(StrictModel):
    id: Key
    description: Description


class AudienceLayer(StrictModel):
    id: Key
    description: Description
    options: list[AudienceOption] = Field(min_length=1, max_length=20)


class AudienceBucket(StrictModel):
    id: Key
    selections: dict[Key, Key]
    enabled: bool = True


class AudienceConfig(StrictModel):
    layers: list[AudienceLayer] = Field(min_length=1, max_length=8)
    buckets: list[AudienceBucket] = Field(max_length=48)

    @model_validator(mode="after")
    def references(self):
        layers = {layer.id: layer for layer in self.layers}
        if len(layers) != len(self.layers) or len({b.id for b in self.buckets}) != len(self.buckets):
            raise ValueError("Layer and bucket IDs must be unique")
        for layer in self.layers:
            if len({o.id for o in layer.options}) != len(layer.options):
                raise ValueError("Option IDs must be unique within each layer")
        combinations = set()
        for bucket in self.buckets:
            if set(bucket.selections) != set(layers):
                raise ValueError("Each bucket must select one option from every layer")
            for layer, option in bucket.selections.items():
                if option not in {o.id for o in layers[layer].options}:
                    raise ValueError("Unknown audience option")
            key = tuple(sorted(bucket.selections.items()))
            if key in combinations:
                raise ValueError("Duplicate bucket combination")
            combinations.add(key)
        return self

    def targets(self):
        return [{"bucket_id": bucket.id, "layers": [
            {"id": layer.id, "description": layer.description,
             "option": next(o.model_dump() for o in layer.options if o.id == bucket.selections[layer.id])}
            for layer in self.layers]} for bucket in self.buckets if bucket.enabled]


class NeutralNarrative(StrictModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    id: str = Field(min_length=1, max_length=100)
    revision: int = Field(default=1, ge=1)
    match_id: str = Field(min_length=1, max_length=100)
    minute: int = Field(ge=0, le=150)
    text: str = Field(min_length=1, max_length=4000)
    # Authoritative context, not inferred by the framing model.
    teams: dict[Annotated[str, Field(max_length=30)], Annotated[str, Field(max_length=100)]] = Field(default_factory=dict, max_length=3)
    evidence: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=20)


class FramedText(StrictModel):
    bucket_id: Key
    text: str = Field(min_length=1, max_length=4000)


class FramingResponse(StrictModel):
    variants: list[FramedText] = Field(min_length=1, max_length=48)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
