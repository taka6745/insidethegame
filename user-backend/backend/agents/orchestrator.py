"""The question agent defines meaning and chooses existing stats before custom work."""
import json

from backend.adapters.llm import JsonModel
from .models import Clarification, GoalDecision
from .semantics import (GOAL_INSTRUCTIONS, STRUCTURED_GOAL_INSTRUCTIONS,
                        DATA_GOAL_INSTRUCTIONS, DATA_STRUCTURED_INSTRUCTIONS)
from .contracts import decision_contract, strict_decision_contract, decision_envelope_model
from .data_skill import EventDataSkill


class GoalAgent:
    def __init__(self, model: JsonModel, *, instructions: str | None = None, compact_contract: bool = True,
                 response_mode: str = "prompt", data_skill: EventDataSkill | None = None):
        self.model = model
        self.data_skill = data_skill
        if response_mode not in {"prompt", "schema"}:
            raise ValueError("Goal response mode must be prompt or schema")
        self.response_mode = response_mode
        prompt_instructions, structured_instructions = (
            (DATA_GOAL_INSTRUCTIONS, DATA_STRUCTURED_INSTRUCTIONS) if data_skill else
            (GOAL_INSTRUCTIONS, STRUCTURED_GOAL_INSTRUCTIONS))
        self.instructions = instructions if instructions is not None else (
            structured_instructions if response_mode == "schema" else prompt_instructions)
        self.schema = (strict_decision_contract() if response_mode == "schema" else
                       decision_contract() if compact_contract else GoalDecision.model_json_schema())

    async def define(self, prompt: str, context: dict) -> GoalDecision:
        payload = {"request": prompt, "context": context, "decision_schema": self.schema}
        if self.data_skill is not None:
            payload["data_skill"] = self.data_skill.context()
        if self.response_mode == "schema":
            result = await self.model.complete(self.instructions, payload, response_schema=self.schema)
            result = decision_envelope_model().model_validate_json(
                json.dumps(result), strict=True).model_dump(mode="json")["decision"]
        else:
            result = await self.model.complete(self.instructions, payload)
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
