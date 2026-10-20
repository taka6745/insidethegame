"""Read-only service API; catalogue editing is confined to the local dev API."""
from fastapi import APIRouter, Header, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from ..models.audiences import AudienceConfig, AudienceSnapshot, StrictModel


class ReplaceAudienceConfig(StrictModel):
    expected_revision: int = Field(ge=1, le=2147483646)
    config: AudienceConfig


def audience_router(service, *, enable_dev_feed):
    router = APIRouter(tags=['Audience configuration'])

    @router.get('/matches/{match_id}/audience-config', response_model=AudienceSnapshot,
                responses={304: {'description': 'Catalogue unchanged; reuse the cached revision'}})
    async def read(match_id: str, if_none_match: str | None = Header(default=None)):
        document, etag = await service.read(match_id)
        headers = {'ETag': etag, 'Cache-Control': 'no-cache'}
        candidates = [item.strip().removeprefix('W/') for item in (if_none_match or '').split(',')]
        if etag in candidates or '*' in candidates:
            return Response(status_code=304, headers=headers)
        return JSONResponse(document, headers=headers)

    if enable_dev_feed:
        @router.put('/dev/matches/{match_id}/audience-config')
        async def replace(match_id: str, body: ReplaceAudienceConfig):
            revision = await service.replace(match_id, body.config, body.expected_revision)
            return {'revision': revision}

    return router
