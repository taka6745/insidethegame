"""Lab chat per match: the same question use cases as the viewer, without its projection."""
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.models.events import MAX_MATCH_EVENTS


VIEWER_ID = r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'  # random UUID (122 random bits)


class SessionRequest(BaseModel):
    """The lab's session: one shared conversation per (profile, match)."""
    model_config = ConfigDict(extra='forbid')
    profile_id: str = Field(min_length=1, max_length=100)
    viewer_id: str = Field(default='', pattern=r'^$')


class ViewerSessionRequest(SessionRequest):
    """One browser's anonymous id: separate browsers are separate viewers. It reopens that browser's conversation,
    so it must be an unguessable random UUID (`match/viewer-id.ts`)."""
    viewer_id: str = Field(pattern=VIEWER_ID)


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str = Field(min_length=1, max_length=2000)
    request_id: UUID
    # The snapshot seq the viewer's picture shows; answers are capped there.
    seq: int | None = Field(default=None, ge=0, le=MAX_MATCH_EVENTS)


def question_router(service):
    router = APIRouter(prefix='/lab', tags=['Questions'])

    @router.get('/chat/profiles')
    async def profiles():
        return await service.profiles()

    router.include_router(match_chat_router(service))
    return router


def match_chat_router(service):
    router = APIRouter(prefix='/matches/{match_id}/chat')

    @router.post('/sessions')
    async def start(match_id: str, body: SessionRequest):
        return await service.start(match_id, body.profile_id, body.viewer_id)

    @router.get('/{token}')
    async def read(match_id: str, token: UUID):
        return await service.read(match_id, token)

    @router.post('/{token}/messages')
    async def ask(match_id: str, token: UUID, body: MessageRequest):
        return await service.ask(match_id, token, body.request_id, body.prompt, body.seq)

    @router.get('/{token}/turns/{turn_id}/replay/{page}')
    async def replay_page(match_id: str, token: UUID, turn_id: int, page: int):
        return await service.replay_page(match_id, token, turn_id, page)

    @router.post('/{token}/offers/{offer_id}/track')
    async def track(match_id: str, token: UUID, offer_id: UUID):
        return await service.track(match_id, token, offer_id)

    return router
