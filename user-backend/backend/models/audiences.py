"""Versioned audience catalogue: definitions only, never narrative authoring."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Key = Annotated[str, Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')]
BucketId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_:-]{0,99}$")]
Description = Annotated[str, Field(min_length=1, max_length=600)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudienceOption(StrictModel):
    id: Key
    description: Description
    # Viewer-facing name; `{home}` and `{away}` become the match's team names.
    label: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    # The side this option backs. Unset: the engine reads a label naming only `{home}` or `{away}`.
    team: Literal["home", "away"] | None = None
    # False: left out of the viewer's bucket name (a layer's default option, e.g. Standard length).
    in_label: bool | None = None


class AudienceLayer(StrictModel):
    id: Key
    description: Description
    options: list[AudienceOption] = Field(min_length=1, max_length=20)


class AudienceBucket(StrictModel):
    id: BucketId
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
        return [{"bucket_id": bucket.id, "selections": bucket.selections, "layers": [
            {"id": layer.id, "description": layer.description,
             "option": next(o.model_dump(exclude_none=True) for o in layer.options if o.id == bucket.selections[layer.id])}
            for layer in self.layers]} for bucket in self.buckets if bucket.enabled]


class GenerationLayer(StrictModel):
    id: Key
    description: Description
    option: AudienceOption


class GenerationTarget(StrictModel):
    bucket_id: BucketId
    selections: dict[Key, Key]
    layers: list[GenerationLayer]


class AudienceSnapshot(AudienceConfig):
    schema_version: Literal[1] = 1
    match_id: str
    revision: int = Field(ge=1)
    generation_targets: list[GenerationTarget]
