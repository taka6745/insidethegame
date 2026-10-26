"""Story follows: the viewer's follow routes under its product session, and the engine's read-only targets."""
from uuid import UUID

from fastapi import APIRouter, Header, Query

from backend.models.events import MAX_MATCH_EVENTS
from backend.models.subscriptions import FollowRequest
from backend.routes.audiences import cached_json
from backend.routes.questions import MessageRequest


def subscription_router(service):
    router = APIRouter(tags=['Story follows'])
    session = '/product/matches/{match_id}/sessions/{token}'

    @router.get(session + '/follows')
    async def listing(match_id: str, token: UUID):
        """The active follow (or null), every follow of this viewer and the follow-chat turns."""
        return await service.listing(match_id, token)

    @router.post(session + '/follows')
    async def follow(match_id: str, token: UUID, body: FollowRequest):
        return await service.follow(match_id, token, body.spec, body.seq, body.match_id)

    @router.delete(session + '/follows/{subscription_id}')
    async def unfollow(match_id: str, token: UUID, subscription_id: UUID):
        return await service.unfollow(match_id, token, subscription_id)

    @router.get(session + '/follow/suggestions')
    async def suggestions(match_id: str, token: UUID, seq: int | None = Query(default=None, ge=0, le=MAX_MATCH_EVENTS)):
        return await service.suggestions(match_id, token, seq)

    @router.post(session + '/follow/messages')
    async def chat(match_id: str, token: UUID, body: MessageRequest):
        return await service.chat(match_id, token, body.request_id, body.prompt, body.seq)

    @router.get('/matches/{match_id}/subscription-targets',
                responses={304: {'description': 'Targets unchanged; reuse the cached revision'}})
    async def targets(match_id: str, if_none_match: str | None = Header(default=None)):
        """Read-only, for the narrative engine (local/README.md Contracts §8b)."""
        return cached_json(*await service.targets(match_id), if_none_match)

    return router
