"""Microsoft Agent Framework workflow with typed routing and bounded repair."""
import asyncio
import os

from agent_framework import WorkflowBuilder

from backend.adapters.llm import LocalJsonModel
from .compiler import StructuredRuleCompiler, RuleHarness
from .fixtures import FixtureCodingAgent, FixtureGoalAgent
from .models import ConversationMessage, PlanOutcome
from .settings import AgentSettings
from .orchestrator import GoalAgent
from .workflow_steps import DefineGoal, GenerateRule, PlanningRequest, ValidateRule
from .data_skill import EventDataSkill


class RuleWorkflow:
    def __init__(self, orchestrator, coder, source="local", harness=None, timeout_seconds=60, max_repairs=3):
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

    async def plan(self, prompt: str, match_context: dict, history: list[dict] | None = None) -> PlanOutcome:
        if not prompt.strip() or len(prompt) > 2000 or not match_context.get("match_id"):
            return PlanOutcome(status="failed", source=self.source, message="Provide a request and an active match.")
        try:
            messages = [ConversationMessage.model_validate(row) for row in (history or [])]
            if len(messages) > 6 or sum(len(row.content) for row in messages) > 6000:
                raise ValueError("Conversation too long")
        except ValueError:
            return PlanOutcome(status="failed", source=self.source, message="Start a new calculation request.")
        context = {**match_context, "conversation": [row.model_dump() for row in messages]}
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.build().run(PlanningRequest(prompt, context))
                outputs = result.get_outputs()
                if len(outputs) != 1 or not isinstance(outputs[0], PlanOutcome):
                    return PlanOutcome(status="failed", source=self.source, message="The agent workflow returned no validated result.")
                return outputs[0]
        except TimeoutError:
            return PlanOutcome(status="failed", source=self.source, message="The calculation request timed out. Please try again.")


def workflow_from_env(*, data_reference: dict | None = None) -> RuleWorkflow:
    mode = os.getenv("LOCAL_LLM_MODE", "fixture")
    settings = AgentSettings.from_env()
    max_repairs = settings.max_repairs
    timeout = float(os.getenv("AGENT_PLAN_TIMEOUT_SECONDS", "60"))
    if not 1 <= timeout <= 300:
        raise ValueError("AGENT_PLAN_TIMEOUT_SECONDS must be between 1 and 300")
    if mode == "fixture":
        return RuleWorkflow(FixtureGoalAgent(), FixtureCodingAgent(), source="fixture", max_repairs=max_repairs, timeout_seconds=timeout)
    if mode == "local":
        if settings.data_skill == "feed" and data_reference is None:
            raise ValueError("The active event adapter must supply the agent data reference")
        skill = EventDataSkill(data_reference) if settings.data_skill == "feed" else None
        return RuleWorkflow(GoalAgent(LocalJsonModel.from_env(name="question_goal"), response_mode=settings.goal_output_mode,
                                      data_skill=skill),
                            StructuredRuleCompiler(), source="local", max_repairs=max_repairs, timeout_seconds=timeout)
    raise ValueError("LOCAL_LLM_MODE must be fixture or local")
