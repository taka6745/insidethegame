"""Thin HTTP layer for the removable question lab."""
from uuid import UUID
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

class SessionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: str = Field(min_length=1,max_length=100)

class MessageRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str = Field(min_length=1,max_length=2000)
    request_id: UUID


def question_router(service):
    router = APIRouter(prefix='/lab/chat',tags=['Questions'])
    @router.get('/profiles')
    async def profiles():
        return await service.profiles()
    @router.post('/sessions')
    async def start(body: SessionRequest):
        return await service.start(body.profile_id)
    @router.get('/{token}')
    async def read(token: UUID):
        return await service.read(token)
    @router.post('/{token}/messages')
    async def ask(token: UUID,body: MessageRequest):
        return await service.ask(token,body.request_id,body.prompt)
    @router.post('/{token}/offers/{offer_id}/track')
    async def track(token: UUID,offer_id: UUID):
        return await service.track(token,offer_id)
    return router
