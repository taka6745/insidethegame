"""Coding agent emits a bounded DSL. No Python, regex or SQL is evaluated."""
from backend.adapters.llm import JsonModel
from backend.models.rules import Rule
from backend.models.events import Event
from .models import Goal


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
    """Independent goal-to-rule comparison rejects valid syntax with the wrong meaning."""
    def validate(self, goal: Goal, match_id: str, candidate: Rule) -> None:
        expected = goal.target_rule(match_id)
        if candidate.calculation_id != expected.calculation_id:
            raise ValueError("Rule does not exactly preserve the goal's operation, entities and time boundaries")
        # Exercise contributions on a representative event, time edges and a different match.
        # Expected meaning is established by the goal, never supplied by the coding model.
        base = {"event_id": "validation", "match_id": match_id,
                "event_type": next(iter(goal.event_types), "pass"),
                "team_id": next(iter(goal.team_ids), None),
                "player_id": next(iter(goal.player_ids), None), "body_part": goal.body_part,
                "period": goal.period or 1, "outcome": goal.outcome,
                "distance_metres": 12.5, "match_time_seconds": 0}
        times = {0, 5400}
        for edge in (goal.after_seconds, goal.from_seconds, goal.before_seconds, goal.through_seconds):
            if edge is not None:
                times.update(t for t in (int(edge) - 1, int(edge), int(edge) + 1) if 0 <= t <= 12000)
        events = [Event(**{**base, "match_time_seconds": time}) for time in times]
        events.append(Event(**{**base, "match_id": "other-match"}))
        events.append(Event(**{**base, "deleted": True}))
        if any(candidate.contribution(event) != expected.contribution(event) for event in events):
            raise ValueError("Rule returned incorrect results for goal examples")
