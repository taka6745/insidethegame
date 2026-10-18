"""Microsoft Agent Framework workflow with typed routing and bounded repair."""
import asyncio
import os

from agent_framework import WorkflowBuilder

from backend.adapters.llm import LocalJsonModel
from .compiler import RuleCodingAgent, RuleHarness
from .fixtures import FixtureCodingAgent, FixtureGoalAgent
from .models import PlanOutcome
from .settings import AgentSettings
from .orchestrator import GoalAgent
from .workflow_steps import DefineGoal, GenerateRule, PlanningRequest, ValidateRule


class RuleWorkflow:
    def __init__(self, orchestrator, coder, source="local", harness=None, timeout_seconds=150, max_repairs=3):
        self.orchestrator, self.coder = orchestrator, coder
        self.source = source
        self.harness = harness or RuleHarness()
        self.timeout_seconds = timeout_seconds
        self.max_repairs = AgentSettings(max_repairs).max_repairs

    def build(self):
        # A new graph per request prevents session or executor state leaking across viewers.
        goal = DefineGoal(self.orchestrator, self.source)
        code = GenerateRule(self.coder)
        validate = ValidateRule(self.harness, self.source, self.max_repairs)
        return (WorkflowBuilder(name="custom_stat", start_executor=goal, output_from=[goal, validate],
                                max_iterations=2 * (self.max_repairs + 1) + 4)
                .add_edge(goal, code)
                .add_edge(code, validate)
                .add_edge(validate, code)
                .build())

    async def plan(self, prompt: str, match_context: dict) -> PlanOutcome:
        if not prompt.strip() or len(prompt) > 2000 or not match_context.get("match_id"):
            return PlanOutcome(status="failed", source=self.source, message="Provide a request and an active match.")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.build().run(PlanningRequest(prompt, match_context))
                outputs = result.get_outputs()
                if len(outputs) != 1 or not isinstance(outputs[0], PlanOutcome):
                    return PlanOutcome(status="failed", source=self.source, message="The agent workflow returned no validated result.")
                return outputs[0]
        except TimeoutError:
            return PlanOutcome(status="failed", source=self.source, message="The calculation request timed out. Please try again.")


def workflow_from_env() -> RuleWorkflow:
    mode = os.getenv("LOCAL_LLM_MODE", "fixture")
    max_repairs = AgentSettings.from_env().max_repairs
    if mode == "fixture":
        return RuleWorkflow(FixtureGoalAgent(), FixtureCodingAgent(), source="fixture", max_repairs=max_repairs)
    if mode == "local":
        return RuleWorkflow(GoalAgent(LocalJsonModel.from_env(name="question_goal")),
                            RuleCodingAgent(LocalJsonModel.from_env(name="rule_coder")), source="local", max_repairs=max_repairs)
    raise ValueError("LOCAL_LLM_MODE must be fixture or local")
