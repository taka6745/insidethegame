"""Backend-wide bounded agent retry configuration."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSettings:
    max_repairs: int = 3

    def __post_init__(self):
        if type(self.max_repairs) is not int or not 0 <= self.max_repairs <= 20:
            raise ValueError("AGENT_MAX_REPAIRS must be an integer from 0 to 20")

    @classmethod
    def from_env(cls):
        try:
            return cls(max_repairs=int(os.getenv("AGENT_MAX_REPAIRS", "3")))
        except ValueError:
            raise ValueError("AGENT_MAX_REPAIRS must be an integer from 0 to 20") from None
