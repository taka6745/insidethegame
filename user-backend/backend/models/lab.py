"""Input contracts for the removable development lab."""
from pydantic import BaseModel, ConfigDict, Field
from backend.models.rules import Rule


class AddCalculation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule: Rule
    label: str = Field(default="Custom statistic", min_length=1, max_length=160)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)


class StartReplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval_ms: int = Field(default=500, ge=50, le=5000)
