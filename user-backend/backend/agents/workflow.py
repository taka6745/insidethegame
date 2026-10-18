"""Application service: semantic planning, generation, validation, bounded repair."""
import asyncio
import os
import logging

from backend.adapters.llm import LocalJsonModel, ModelError
from .compiler import RuleCodingAgent, RuleHarness
from .fixtures import FixtureCodingAgent, FixtureGoalAgent
from .models import PlanOutcome
from .orchestrator import GoalAgent


class RuleWorkflow:
    def __init__(self, orchestrator, coder, source="local", harness=None, timeout_seconds=150):
        self.orchestrator, self.coder = orchestrator, coder
        self.source = source
        self.harness = harness or RuleHarness()
        self.timeout_seconds = timeout_seconds

    async def plan(self, prompt: str, match_context: dict) -> PlanOutcome:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._plan(prompt, match_context)
        except TimeoutError:
            return PlanOutcome(status="failed", source=self.source, message="The calculation request timed out. Please try again.")

    async def _plan(self, prompt: str, match_context: dict) -> PlanOutcome:
        if not prompt.strip() or len(prompt) > 2000 or not match_context.get("match_id"):
            return PlanOutcome(status="failed", source=self.source, message="Provide a request and an active match.")
        decision = None
        # One retry handles transient routing failures or malformed goal output. It
        # stays inside the same overall deadline and never switches to fixture mode.
        for goal_attempt in range(2):
            try:
                decision = await self.orchestrator.define(prompt, match_context)
                break
            except (ModelError, ValueError) as exc:
                reason = exc.reason if isinstance(exc, ModelError) else "goal_schema"
                logging.getLogger(__name__).warning("Goal definition failed: reason=%s attempt=%s", reason, goal_attempt + 1)
                if isinstance(exc, ModelError) and not exc.retryable:
                    break
        if decision is None:
            return PlanOutcome(status="failed", source=self.source, message="Could not define a validated goal. Please try again.")
        if decision.status != "custom":
            return PlanOutcome(status=decision.status, source=self.source, goal=decision.goal,
                               standard_stat_id=decision.standard_stat_id, message=decision.message)
        feedback = None
        for attempt in range(1, 5):
            try:
                rule = await self.coder.generate(decision.goal, match_context["match_id"], feedback)
                self.harness.validate(decision.goal, match_context["match_id"], rule)
                return PlanOutcome(status="ready", source=self.source, goal=decision.goal,
                                   rule=rule, attempts=attempt, message="Structured rule validated against the goal.")
            except (ModelError, ValueError) as exc:
                # Only local validation feedback; no network response body enters another prompt.
                feedback = str(exc)[:1500]
        return PlanOutcome(status="failed", source=self.source, goal=decision.goal, attempts=4,
                           message="Could not validate the calculation after three repairs.")


def workflow_from_env() -> RuleWorkflow:
    mode = os.getenv("LOCAL_LLM_MODE", "fixture")
    if mode == "fixture":
        return RuleWorkflow(FixtureGoalAgent(), FixtureCodingAgent(), source="fixture")
    if mode == "local":
        model = LocalJsonModel.from_env()
        return RuleWorkflow(GoalAgent(model), RuleCodingAgent(model), source="local")
    raise ValueError("LOCAL_LLM_MODE must be fixture or local")
