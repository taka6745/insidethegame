"""Engine-facing prompt reads; version editing only behind the local dev flag."""
from fastapi import APIRouter, Header, Path

from backend.models.prompts import Role, SavePrompt
from backend.routes.audiences import cached_json


def prompt_router(service, *, enable_dev_feed):
    router = APIRouter(tags=['Narrative prompts'])

    @router.get('/narrative-prompts', responses={304: {'description': 'Prompts unchanged'}})
    async def read(if_none_match: str | None = Header(default=None)):
        return cached_json(*await service.read(), if_none_match)

    if enable_dev_feed:
        @router.get('/dev/narrative-prompts')
        async def versions():
            return await service.versions()

        @router.put('/dev/narrative-prompts/{role}')
        async def save(role: Role, body: SavePrompt):
            return await service.save(role, body.template, body.expected_version)

        @router.post('/dev/narrative-prompts/{role}/versions/{version}/activate')
        async def activate(role: Role, version: int = Path(ge=1, le=2147483646)):
            return await service.activate(role, version)

    return router
