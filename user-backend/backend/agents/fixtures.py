"""Explicit account-free examples, not a substitute presented as model intelligence."""
import unicodedata
import json
from pathlib import Path

from .models import Goal, GoalDecision


def normalized(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.lower())
                            if not unicodedata.combining(c)).split()).rstrip(".?!")


class FixtureGoalAgent:
    # Exact phrases make unsupported requests visible instead of silently dropping conditions.
    async def define(self, prompt: str, context: dict) -> GoalDecision:
        phrases = {
            "track total headers in this game by mbappe": {"player_ids": ("mbappe",), "body_part": "head"},
            "track mbappe's headers": {"player_ids": ("mbappe",), "body_part": "head"},
            "track mbappe's headed shots": {"player_ids": ("mbappe",), "body_part": "head", "event_types": ("shot", "goal")},
            "track chelsea's corners after the 60th minute": {"team_ids": ("chelsea",), "event_types": ("corner",), "after_seconds": 3600},
            "corners after the 60th minute": {"event_types": ("corner",), "after_seconds": 3600},
            "corners after the 70th minute": {"event_types": ("corner",), "after_seconds": 4200},
            "track second-half corners": {"event_types": ("corner",), "period": 2},
            "track headers since minute 20": {"body_part": "head", "from_seconds": 1200},
            "track total chelsea pass distance": {"team_ids": ("chelsea",), "event_types": ("pass",), "operation": "sum", "sum_field": "distance_metres"},
        }
        data = phrases.get(normalized(prompt))
        if data is None:
            data = self._preset_goal(prompt)
        if data is None:
            return GoalDecision(status="unsupported", message="Fixture mode supports the listed sample requests. Configure a local model for other wording.")
        goal = Goal(description=prompt, **data)
        for field, collection in (("player_ids", "players"), ("team_ids", "teams")):
            if not set(getattr(goal, field)) <= {item["id"] for item in context.get(collection, [])}:
                return GoalDecision(status="clarification", message="The requested player or team is not in this match.")
        return GoalDecision(status="custom", goal=goal)

    @staticmethod
    def _preset_goal(prompt):
        path = Path(__file__).resolve().parents[2] / "fixtures" / "filter-lab.json"
        for preset in json.loads(path.read_text())["presets"]:
            if normalized(preset["label"]) != normalized(prompt):
                continue
            rule = preset["rule"]
            data = {"operation": rule["operation"], "sum_field": rule.get("sum_field")}
            for predicate in rule.get("predicates", []):
                field, op, value = predicate["field"], predicate["op"], predicate["value"]
                if field in {"event_type", "team_id", "player_id"}:
                    data[{"event_type": "event_types", "team_id": "team_ids", "player_id": "player_ids"}[field]] = value if op == "in" else [value]
                elif field == "match_time_seconds":
                    data[{"gt": "after_seconds", "gte": "from_seconds", "lt": "before_seconds", "lte": "through_seconds"}[op]] = value
                else:
                    data[field] = value
            return data
        return None


class FixtureCodingAgent:
    async def generate(self, goal: Goal, match_id: str, feedback: str | None = None):
        return goal.target_rule(match_id)
