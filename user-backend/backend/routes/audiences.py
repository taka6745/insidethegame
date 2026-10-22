"""Read-only audience API for the narrative engine; template editing only behind the local dev flag."""
from fastapi import APIRouter, Header, Path, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from ..models.audiences import AudienceConfig, AudienceSnapshot, StrictModel

Fixture = Path(pattern=r'^[a-z0-9-]{1,55}$')


def cached_json(document, etag, if_none_match):
    """Strong ETag with 304 on any matching If-None-Match candidate."""
    headers = {'ETag': etag, 'Cache-Control': 'no-cache'}
    candidates = [item.strip().removeprefix('W/') for item in (if_none_match or '').split(',')]
    if etag in candidates or '*' in candidates:
        return Response(status_code=304, headers=headers)
    return JSONResponse(document, headers=headers)


class ReplaceAudienceConfig(StrictModel):
    expected_revision: int = Field(ge=1, le=2147483646)
    config: AudienceConfig


def audience_router(service, *, enable_dev_feed):
    router = APIRouter(tags=['Audience configuration'])

    @router.get('/matches/{match_id}/audience-config', response_model=AudienceSnapshot,
                responses={304: {'description': 'Catalogue unchanged; reuse the cached revision'}})
    async def read(match_id: str, if_none_match: str | None = Header(default=None)):
        return cached_json(*await service.read(match_id), if_none_match)

    if enable_dev_feed:
        @router.get('/dev/fixtures/{fixture}/audience-config')
        async def template(fixture: str = Fixture):
            return await service.template(fixture)

        @router.put('/dev/fixtures/{fixture}/audience-config')
        async def replace(body: ReplaceAudienceConfig, fixture: str = Fixture):
            return {'revision': await service.replace_template(fixture, body.config, body.expected_revision)}

        @router.get('/dev/audience-templates')
        async def templates():
            return await service.templates()

    return router
