"""Local development configuration/ingress; viewer selection uses existing sessions."""
from uuid import UUID

from fastapi import APIRouter
from pydantic import Field

from ..models.narratives import AudienceConfig, Key, NeutralNarrative, StrictModel


class ConfigureAudiences(StrictModel):
    expected_revision: int = Field(ge=1)
    config: AudienceConfig


class SelectAudience(StrictModel):
    selections: dict[Key, Key] = Field(max_length=8)


def narrative_router(service, notify_all, snapshot, *, enable_dev_feed):
    router = APIRouter()

    @router.get('/audiences')
    async def audiences():
        return await service.configuration()

    @router.put('/sessions/{token}/audience')
    async def select(token: UUID, body: SelectAudience):
        await service.select_viewer(token, body.selections)
        await notify_all('audience_changed')
        return await snapshot(token)

    if enable_dev_feed:
        @router.put('/dev/audiences')
        async def configure(body: ConfigureAudiences):
            revision = await service.configure(body.config, body.expected_revision)
            await notify_all('audience_configuration_changed')
            return {'revision': revision}

        @router.post('/dev/neutral-narratives', status_code=202)
        async def receive(body: NeutralNarrative):
            result = await service.receive(body)
            await notify_all('neutral_narrative_received')
            return result

    return router
