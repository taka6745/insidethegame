"""Typed Microsoft Agent Framework executors for goal, generation and repair."""
import logging
import time
from dataclasses import dataclass, replace

from agent_framework import Executor, WorkflowContext, handler
from pydantic import ValidationError

from backend.adapters.llm import ModelError
from backend.models.rules import Rule
from .models import Goal, PlanOutcome
from .clarification import unresolved_player


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
    goal_seconds: float = 0
    model_calls: int = 0
    coding_seconds: float = 0
    goal_failure_reasons: tuple[str, ...] = ()
    goal_validation_errors: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Candidate:
    request: CodingRequest
    rule: Rule | None = None
    error: str | None = None
    retryable: bool = True
    seconds: float = 0


class DefineGoal(Executor):
    def __init__(self, agent, source):
        super().__init__(id="define_goal")
        self.agent, self.source = agent, source

    @handler
    async def handle(self, request: PlanningRequest, ctx: WorkflowContext[CodingRequest, PlanOutcome]):
        start = time.perf_counter()
        context = dict(request.context)
        decision = unresolved_player(request.prompt, context)
        calls = 0
        failures = []
        validation_errors = []
        for attempt in range(0 if decision is not None else 2):
            try:
                calls += int(hasattr(self.agent, "model"))
                decision = await self.agent.define(request.prompt, context)
                break
            except (ModelError, ValueError) as exc:
                if isinstance(exc, ValidationError):
                    safe_errors = []
                    for error in exc.errors(include_url=False, include_context=False, include_input=False)[:12]:
                        location = list(error["loc"])
                        # Unknown keys are model output too; do not publish their contents.
                        if error["type"] == "extra_forbidden" and location:
                            location[-1] = "<extra>"
                        safe_errors.append({"path": ".".join(str(part) for part in location)[:256],
                                            "type": error["type"]})
                    context["goal_validation_errors"] = safe_errors
                    validation_errors.extend({"attempt": attempt + 1, **error} for error in safe_errors)
                reason = exc.reason if isinstance(exc, ModelError) else "goal_schema"
                failures.append(reason)
                logging.getLogger(__name__).warning("Goal definition failed: reason=%s attempt=%s", reason, attempt + 1)
                if isinstance(exc, ModelError) and not exc.retryable:
                    break
        seconds = round(time.perf_counter() - start, 3)
        if decision is None:
            await ctx.yield_output(PlanOutcome(status="failed", source=self.source,
                                              model_calls=calls, stage_seconds={"goal": seconds},
                                              goal_failure_reasons=failures, goal_validation_errors=validation_errors,
                                              message="Could not define a validated goal. Please try again."))
        elif decision.status != "custom":
            await ctx.yield_output(PlanOutcome(status=decision.status, source=self.source, goal=decision.goal,
                                              standard_stat_id=decision.standard_stat_id, clarification=decision.clarification, message=decision.message,
                                              model_calls=calls, goal_failure_reasons=failures, goal_validation_errors=validation_errors, stage_seconds={"goal": seconds}))
        else:
            await ctx.send_message(CodingRequest(decision.goal, request.context["match_id"], goal_seconds=seconds,
                                                 model_calls=calls, goal_failure_reasons=tuple(failures),
                                                 goal_validation_errors=tuple(validation_errors)))


class GenerateRule(Executor):
    def __init__(self, agent):
        super().__init__(id="generate_rule")
        self.agent = agent

    @handler
    async def handle(self, request: CodingRequest, ctx: WorkflowContext[Candidate]):
        start = time.perf_counter()
        request = replace(request, model_calls=request.model_calls + int(hasattr(self.agent, "model")))
        try:
            rule = await self.agent.generate(request.goal, request.match_id, request.feedback)
            candidate = Candidate(request, rule=rule)
        except (ModelError, ValueError) as exc:
            # Provider errors are sanitised by the adapter; schema errors never send
            # provider bodies or rejected model values into a subsequent prompt.
            error = str(exc) if isinstance(exc, ModelError) else "Generated rule does not match the supported schema."
            candidate = Candidate(request, error=error,
                                  retryable=not isinstance(exc, ModelError) or exc.retryable)
        candidate = replace(candidate, seconds=time.perf_counter() - start)
        await ctx.send_message(candidate)


class ValidateRule(Executor):
    def __init__(self, harness, source, max_repairs=3):
        super().__init__(id="validate_rule")
        self.harness, self.source = harness, source
        self.max_repairs = max_repairs

    @handler
    async def handle(self, candidate: Candidate, ctx: WorkflowContext[CodingRequest, PlanOutcome]):
        request, error = candidate.request, candidate.error
        validation_start = time.perf_counter()
        coding_seconds = request.coding_seconds + candidate.seconds
        if error is None:
            try:
                self.harness.validate(request.goal, request.match_id, candidate.rule)
            except ValueError as exc:
                error = str(exc)[:1500]
        coding_seconds += time.perf_counter() - validation_start
        if error is None:
            await ctx.yield_output(PlanOutcome(status="ready", source=self.source, goal=request.goal,
                                              rule=candidate.rule, attempts=request.attempt,
                                              model_calls=request.model_calls, stage_seconds={"goal": request.goal_seconds, "compile_validate": round(coding_seconds, 3)},
                                              goal_failure_reasons=list(request.goal_failure_reasons),
                                              goal_validation_errors=list(request.goal_validation_errors),
                                              message="Structured rule validated against the goal."))
        elif candidate.retryable and request.attempt <= self.max_repairs:
            await ctx.send_message(replace(request, attempt=request.attempt + 1, feedback=error, coding_seconds=coding_seconds))
        else:
            message = (f"Could not validate the calculation after {self.max_repairs} repairs." if candidate.retryable
                       else "The model request was rejected. Check the local model configuration.")
            await ctx.yield_output(PlanOutcome(status="failed", source=self.source, goal=request.goal,
                                              attempts=request.attempt, message=message, model_calls=request.model_calls,
                                              goal_failure_reasons=list(request.goal_failure_reasons),
                                              goal_validation_errors=list(request.goal_validation_errors),
                                              stage_seconds={"goal": request.goal_seconds, "compile_validate": round(coding_seconds, 3)}))
