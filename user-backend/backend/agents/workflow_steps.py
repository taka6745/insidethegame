"""Typed Microsoft Agent Framework executors for goal, generation and repair."""
import logging
from dataclasses import dataclass

from agent_framework import Executor, WorkflowContext, handler

from backend.adapters.llm import ModelError
from backend.models.rules import Rule
from .models import Goal, PlanOutcome


@dataclass(frozen=True)
class PlanningRequest:
    prompt: str
    context: dict


@dataclass(frozen=True)
class CodingRequest:
    goal: Goal
    match_id: str
    attempt: int = 1
    feedback: str | None = None


@dataclass(frozen=True)
class Candidate:
    request: CodingRequest
    rule: Rule | None = None
    error: str | None = None
    retryable: bool = True


class DefineGoal(Executor):
    def __init__(self, agent, source):
        super().__init__(id="define_goal")
        self.agent, self.source = agent, source

    @handler
    async def handle(self, request: PlanningRequest, ctx: WorkflowContext[CodingRequest, PlanOutcome]):
        decision = None
        for attempt in range(2):
            try:
                decision = await self.agent.define(request.prompt, request.context)
                break
            except (ModelError, ValueError) as exc:
                reason = exc.reason if isinstance(exc, ModelError) else "goal_schema"
                logging.getLogger(__name__).warning("Goal definition failed: reason=%s attempt=%s", reason, attempt + 1)
                if isinstance(exc, ModelError) and not exc.retryable:
                    break
        if decision is None:
            await ctx.yield_output(PlanOutcome(status="failed", source=self.source,
                                              message="Could not define a validated goal. Please try again."))
        elif decision.status != "custom":
            await ctx.yield_output(PlanOutcome(status=decision.status, source=self.source, goal=decision.goal,
                                              standard_stat_id=decision.standard_stat_id, message=decision.message))
        else:
            await ctx.send_message(CodingRequest(decision.goal, request.context["match_id"]))


class GenerateRule(Executor):
    def __init__(self, agent):
        super().__init__(id="generate_rule")
        self.agent = agent

    @handler
    async def handle(self, request: CodingRequest, ctx: WorkflowContext[Candidate]):
        try:
            rule = await self.agent.generate(request.goal, request.match_id, request.feedback)
            candidate = Candidate(request, rule=rule)
        except (ModelError, ValueError) as exc:
            # Provider errors are sanitised by the adapter; schema errors never send
            # provider bodies or rejected model values into a subsequent prompt.
            error = str(exc) if isinstance(exc, ModelError) else "Generated rule does not match the supported schema."
            candidate = Candidate(request, error=error,
                                  retryable=not isinstance(exc, ModelError) or exc.retryable)
        await ctx.send_message(candidate)


class ValidateRule(Executor):
    def __init__(self, harness, source, max_repairs=3):
        super().__init__(id="validate_rule")
        self.harness, self.source = harness, source
        self.max_repairs = max_repairs

    @handler
    async def handle(self, candidate: Candidate, ctx: WorkflowContext[CodingRequest, PlanOutcome]):
        request, error = candidate.request, candidate.error
        if error is None:
            try:
                self.harness.validate(request.goal, request.match_id, candidate.rule)
            except ValueError as exc:
                error = str(exc)[:1500]
        if error is None:
            await ctx.yield_output(PlanOutcome(status="ready", source=self.source, goal=request.goal,
                                              rule=candidate.rule, attempts=request.attempt,
                                              message="Structured rule validated against the goal."))
        elif candidate.retryable and request.attempt <= self.max_repairs:
            await ctx.send_message(CodingRequest(request.goal, request.match_id, request.attempt + 1, error))
        else:
            message = (f"Could not validate the calculation after {self.max_repairs} repairs." if candidate.retryable
                       else "The model request was rejected. Check the local model configuration.")
            await ctx.yield_output(PlanOutcome(status="failed", source=self.source, goal=request.goal,
                                              attempts=request.attempt, message=message))
