"""The question agent defines meaning and chooses existing stats before custom work."""
from backend.adapters.llm import JsonModel
from .models import Clarification, GoalDecision
from .semantics import GOAL_INSTRUCTIONS
from .contracts import decision_contract


class GoalAgent:
    def __init__(self, model: JsonModel, *, instructions: str = GOAL_INSTRUCTIONS, compact_contract: bool = True):
        self.model = model
        self.instructions = instructions
        self.schema = decision_contract() if compact_contract else GoalDecision.model_json_schema()

    async def define(self, prompt: str, context: dict) -> GoalDecision:
        result = await self.model.complete(
            self.instructions,
            {"request": prompt, "context": context, "decision_schema": self.schema},
        )
        decision = GoalDecision.model_validate(result)
        if decision.goal:
            for field, collection in (("player_ids", "players"), ("team_ids", "teams")):
                allowed = {item["id"] for item in context.get(collection, [])}
                if not set(getattr(decision.goal, field)) <= allowed:
                    return GoalDecision(status="clarification", clarification=Clarification(
                        question="Which player or team in this match do you mean?",
                        options=[item.get("name", item["id"]) for item in context.get(collection, [])][:5],
                        missing_fields=["player" if field == "player_ids" else "team"]))
        if decision.status == "reuse":
            if decision.standard_stat_id not in {item["id"] for item in context.get("standard_stats", [])}:
                raise ValueError("Model selected a stat outside the supplied catalogue")
        return decision
