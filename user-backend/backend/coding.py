"""Coding-agent orchestration contract; generated code is NEVER executed here."""
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from .agents.settings import AgentSettings


@dataclass(frozen=True)
class Case:
    name: str
    events: tuple[dict, ...]
    expected: float


@dataclass(frozen=True)
class Goal:
    description: str
    required_fields: frozenset[str]
    cases: tuple[Case, ...]


@dataclass(frozen=True)
class Outcome:
    source: str | None
    attempts: int
    error: str | None


class CodingAgent(Protocol):
    def generate(self, goal: Goal, previous_source: str | None, feedback: str | None) -> str: ...


class Executor(Protocol):
    """Production implementation must enforce isolation, resource limits and allowed GraphQL."""
    def evaluate(self, source: str, cases: tuple[Case, ...]) -> list[float]: ...


def build_calculation(goal, available_fields, agent: CodingAgent, executor: Executor, *, max_repairs=None):
    repairs = AgentSettings.from_env().max_repairs if max_repairs is None else AgentSettings(max_repairs).max_repairs
    if not goal.description.strip() or not goal.cases or not goal.required_fields <= available_fields:
        return Outcome(None, 0, "The goal lacks test cases or the available data cannot support it")
    if any(type(c.expected) not in (int, float) or not math.isfinite(c.expected) for c in goal.cases):
        return Outcome(None, 0, "Expected results must be finite numbers")
    source, feedback = None, None
    # Initial generation plus the configured number of repairs. The calling question agent owns the goal.
    for attempt in range(1, repairs + 2):
        try:
            source = agent.generate(deepcopy(goal), source, feedback)
            if not isinstance(source, str) or not source.strip():
                raise ValueError("No source returned")
            actual = executor.evaluate(source, deepcopy(goal.cases))
            if len(actual) != len(goal.cases):
                raise ValueError("Executor must return one result per goal case")
            failures = [case.name for case, value in zip(goal.cases, actual)
                        if type(value) not in (int, float) or not math.isfinite(value) or value != case.expected]
            if not failures:
                return Outcome(source, attempt, None)
            feedback = "Wrong result for goal cases: " + ", ".join(failures)
        except Exception as exc:
            feedback = f"Validation failed: {type(exc).__name__}: {exc}"
    return Outcome(None, repairs + 1, f"The statistic could not be validated after {repairs} repairs")
