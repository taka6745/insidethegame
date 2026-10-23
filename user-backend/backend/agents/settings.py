"""Agent workflow settings: repairs, goal output mode, data skill and plan timeout."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSettings:
    max_repairs: int = 3
    goal_output_mode: str = "prompt"
    data_skill: str = "off"
    plan_timeout: float = 60

    def __post_init__(self):
        if type(self.max_repairs) is not int or not 0 <= self.max_repairs <= 20:
            raise ValueError("AGENT_MAX_REPAIRS must be an integer from 0 to 20")
        if self.goal_output_mode not in {"prompt", "schema"}:
            raise ValueError("AGENT_GOAL_OUTPUT_MODE must be prompt or schema")
        if self.data_skill not in {"off", "feed"}:
            raise ValueError("AGENT_DATA_SKILL must be off or feed")
        if not 1 <= self.plan_timeout <= 300:
            raise ValueError("AGENT_PLAN_TIMEOUT_SECONDS must be between 1 and 300")

    @classmethod
    def from_env(cls):
        try:
            max_repairs = int(os.getenv("AGENT_MAX_REPAIRS", "3"))
        except ValueError:
            raise ValueError("AGENT_MAX_REPAIRS must be an integer from 0 to 20") from None
        return cls(max_repairs=max_repairs, goal_output_mode=os.getenv("AGENT_GOAL_OUTPUT_MODE", "prompt"),
                   data_skill=os.getenv("AGENT_DATA_SKILL", "off"),
                   plan_timeout=float(os.getenv("AGENT_PLAN_TIMEOUT_SECONDS", "60")))
