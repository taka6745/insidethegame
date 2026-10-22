"""Lab chat per match: the same question use cases as the viewer, without its projection."""
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.models.events import MAX_MATCH_EVENTS


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: str = Field(min_length=1, max_length=100)


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
        return await service.start(match_id, body.profile_id)

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
