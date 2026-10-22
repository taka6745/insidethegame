"""Internal admin API (not proxied publicly): per-match purge (local/contracts.md §5)."""
import logging

from fastapi import APIRouter

from backend.domain import RuleError
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PurgeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    match_id: str | None = Field(default=None, min_length=1, max_length=64)
    all: bool = False

    @model_validator(mode='after')
    def exactly_one(self):
        if (self.match_id is None) == (not self.all):
            raise ValueError('Send exactly one of match_id or all: true')
        return self


def admin_router(registry):
    router = APIRouter(prefix='/admin', tags=['Admin'])

    @router.post('/matches/purge')
    async def purge(body: PurgeRequest):
        try:
            return await registry.purge(None if body.all else body.match_id)
        except Exception as exc:
            logging.getLogger(__name__).warning('Purge failed: %s', type(exc).__name__)
            raise RuleError('purge_failed', 'The purge did not complete; retry it.', 503) from exc

    return router
