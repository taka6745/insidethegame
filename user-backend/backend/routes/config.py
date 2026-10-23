"""Developer editing of backend tunables (local /dev/ API only)."""
from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field

from backend.domain import RuleError
from backend.models.config import ConfigName
from backend.routes.audiences import cached_json


class ReplaceConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int | None = Field(default=None, ge=1, le=2147483646)
    value: dict


def config_router(service):
    router = APIRouter(prefix='/dev/config', tags=['Backend configuration'])

    @router.get('/{table}', responses={304: {'description': 'Configuration unchanged'}})
    async def read(table: ConfigName, if_none_match: str | None = Header(default=None)):
        return cached_json(*await service.document(table), if_none_match)

    @router.put('/{table}')
    async def replace(table: ConfigName, body: ReplaceConfig, if_match: str | None = Header(default=None)):
        """Optimistic: `expected_revision` in the body, or the ETag from GET in If-Match."""
        expected = body.expected_revision
        if expected is None:
            document, etag = await service.document(table)
            if if_match is None:
                raise RuleError('revision_required', 'Send expected_revision or If-Match', 428)
            if if_match.strip().removeprefix('W/') != etag:
                raise RuleError('config_revision_conflict', 'Reload the configuration before saving', 409)
            expected = document['revision']
        return await service.replace(table, body.value, expected)

    return router


def policy_router(service):
    """Engine-facing, read-only: the storyline policy (edited under /dev/config/storyline-policy)."""
    router = APIRouter(tags=['Storyline policy'])

    @router.get('/storyline-policy', responses={304: {'description': 'Policy unchanged'}})
    async def read(if_none_match: str | None = Header(default=None)):
        return cached_json(*await service.document('storyline-policy'), if_none_match)

    @router.get('/model-roles', responses={304: {'description': 'Roles unchanged'}})
    async def models(if_none_match: str | None = Header(default=None)):
        """The engine's model per role (edited under /dev/config/models)."""
        return cached_json(*await service.document('models'), if_none_match)

    return router
