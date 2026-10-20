"""Neutral input and framed output contracts internal to the narrative prototype."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    bucket_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_:-]{0,99}$")]
    text: str = Field(min_length=1, max_length=4000)


class FramingResponse(StrictModel):
    variants: list[FramedText] = Field(min_length=1, max_length=48)
