"""Coding agent emits a bounded DSL. No Python, regex or SQL is evaluated."""
from backend.adapters.llm import JsonModel
from backend.models.rules import Rule
from backend.models.actions import SpadlAction
from backend.agents.models import Goal


class RuleCodingAgent:
    def __init__(self, model: JsonModel):
        self.model = model

    async def generate(self, goal: Goal, match_id: str, feedback: str | None = None) -> Rule:
        response = await self.model.complete(
            "Compile the supplied semantic goal into one JSON rule matching rule_schema. "
            "All predicates are ANDed; multiple alternatives for one field use in. "
            "Do not omit, broaden, add or reinterpret any goal constraint. "
            "after_seconds maps to match_time_seconds gt; from_seconds to gte; "
            "before_seconds to lt; through_seconds to lte. A second half is period eq 2. "
            "Use the exact match_id supplied. Return the rule object only, no code or commentary.",
            {"goal": goal.model_dump(mode="json"), "match_id": match_id,
             "rule_schema": Rule.model_json_schema(), "validation_feedback": feedback},
        )
        return Rule.model_validate(response)


class RuleHarness:
    """Check goal-to-rule agreement; evaluate language understanding separately."""
    def validate(self, goal: Goal, match_id: str, candidate: Rule) -> None:
        expected = goal.target_rule(match_id)
        if candidate.calculation_id != expected.calculation_id:
            raise ValueError("Rule does not exactly preserve the goal's operation, entities and time boundaries")
        if candidate.composite:
            # Exact canonical identity also verifies both independently validated leaves.
            return
        # Exercise contributions on a representative action, time edges and a different match.
        # Expected meaning is established by the goal, never supplied by the coding model.
        bound = lambda field, default: next((b.gte if b.gte is not None else b.lte for b in goal.locations
                                             if b.field == field), default)
        base = {"match_id": match_id, "action_id": 0, "action_type": next(iter(goal.action_types), "pass"),
                "team_id": next(iter(goal.team_ids), "validation-team"),
                "player_id": next(iter(goal.player_ids), None), "bodypart": next(iter(goal.bodyparts), "foot"),
                "bodypart_observed": True, "period": goal.period or 1, "result": next(iter(goal.results), "success"),
                "start_x": bound("start_x", 40.0), "start_y": bound("start_y", 30.0),
                "end_x": bound("end_x", 60.0), "end_y": bound("end_y", 30.0),
                "start_zone": next(iter(goal.start_zones), "middle_third"),
                "end_zone": next(iter(goal.end_zones), "middle_third"), "seq": 1, "final_seq": 1,
                "match_time_seconds": 0}
        times = {0, 5400}
        for edge in (goal.after_seconds, goal.from_seconds, goal.before_seconds, goal.through_seconds):
            if edge is not None:
                times.update(t for t in (int(edge) - 1, int(edge), int(edge) + 1) if 0 <= t <= 12000)
        actions = [SpadlAction(**{**base, "match_time_seconds": time}) for time in times]
        actions.append(SpadlAction(**{**base, "match_id": "other-match"}))
        actions.append(SpadlAction(**{**base, "bodypart_observed": False}))
        if any(candidate.contribution(action) != expected.contribution(action) for action in actions):
            raise ValueError("Rule returned incorrect results for goal examples")


class StructuredRuleCompiler:
    """Compile the bounded goal exactly; no second model call can improve this mapping."""
    async def generate(self, goal: Goal, match_id: str, feedback: str | None = None) -> Rule:
        return goal.target_rule(match_id)
