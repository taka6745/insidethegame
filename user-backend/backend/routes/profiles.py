"""Developer editing of demo profiles (local /dev/ API only), like /dev/config: ETag + expected_revision."""
from fastapi import APIRouter, Header
from pydantic import Field

from backend.models.profiles import DemoProfiles
from backend.routes.audiences import cached_json


class ReplaceProfiles(DemoProfiles):
    expected_revision: int | None = Field(default=None, ge=1, le=2147483646)


def profile_router(service):
    router = APIRouter(prefix='/dev/profiles', tags=['Demo profiles'])

    @router.get('', responses={304: {'description': 'Profiles unchanged'}})
    async def read(if_none_match: str | None = Header(default=None)):
        return cached_json(*await service.document(), if_none_match)

    @router.put('')
    async def replace(body: ReplaceProfiles, if_match: str | None = Header(default=None)):
        return await service.replace([p.model_dump() for p in body.profiles], body.expected_revision, if_match)

    return router
