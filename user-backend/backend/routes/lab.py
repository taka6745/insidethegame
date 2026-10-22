"""Lab HTTP boundary per match: custom calculations over received events. No recordings."""
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.domain import RuleError
from backend.models.rules import Rule


class AddCalculation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rule: Rule
    label: str = Field(default='Custom statistic', min_length=1, max_length=160)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)


def lab_router(registry, planner, product, match_data):
    router = APIRouter(prefix='/lab/matches/{match_id}', tags=['Development filter lab'])

    @router.get('/state')
    async def state(match_id: str):
        match = registry.get(match_id)
        await match_data.info(match)
        # Published ETL goals for the header; never recalculated here or in the browser.
        return {**await match.state(), 'score': product.score(match_id),
                'llm': {'configured': planner is not None}}

    @router.get('/events/{seq}')
    async def event_record(match_id: str, seq: int):
        return registry.get(match_id).event_record(seq)

    @router.post('/calculations', status_code=201)
    async def register(match_id: str, body: AddCalculation):
        match = registry.get(match_id)
        await match_data.info(match)  # The home team first: actions are read team-relative.
        return await match.register(body.rule, body.label)

    @router.post('/plan')
    async def plan(match_id: str, body: PlanRequest):
        if planner is None:
            raise RuleError('model_unavailable', 'Custom stats are unavailable: no model is configured.', 503)
        match = registry.get(match_id)
        await match_data.info(match)
        return await match.plan(planner, body.prompt, body.conversation_id)

    return router
