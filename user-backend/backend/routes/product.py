"""Product transport; shares the established question/session use cases."""
import asyncio
from uuid import UUID

import anyio
from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect
from backend.domain import RuleError
from backend.models.viewer_audience import ViewerAudience
from backend.routes.audiences import cached_json
from backend.routes.questions import ViewerSessionRequest, MessageRequest


async def stream_product(ws, service, match_id, token):
    try:
        peer, snapshot = await service.attach(match_id, token)
    except RuleError as exc:
        # Accept before closing so browsers receive the application close code
        # rather than an opaque HTTP handshake failure.
        await ws.accept()
        await ws.close(code=4404 if exc.code == 'match_not_found' else 4001 if exc.status < 500 else 1013)
        return
    try:
        await ws.accept()
        async with asyncio.timeout(10):
            await ws.send_json(snapshot)

        async def send():
            while True:
                try:
                    message = await asyncio.wait_for(peer.queue.get(), 20)
                except TimeoutError:
                    message = {'type': 'heartbeat'}
                if 'close' in message:
                    await ws.close(code=message['close'])
                    return
                async with asyncio.timeout(10):
                    await ws.send_json(message)

        async def receive():
            while True:
                await ws.receive_text()

        async with anyio.create_task_group() as group:
            async def run(operation):
                try:
                    await operation()
                except (WebSocketDisconnect, TimeoutError):
                    pass
                finally:
                    group.cancel_scope.cancel()
            group.start_soon(run, send)
            await run(receive)
    except (WebSocketDisconnect, TimeoutError):
        pass
    finally:
        with anyio.CancelScope(shield=True):
            await service.detach(match_id, peer)


def product_router(service):
    """Everything per match under /product/matches/{match_id}; a session belongs to one match."""
    router = APIRouter(prefix='/product', tags=['Match viewer'])
    session = '/matches/{match_id}/sessions/{token}'

    @router.get('/matches')
    async def matches():
        return await service.matches()

    @router.get('/profiles')
    async def profiles():
        return await service.profiles()

    @router.get('/prices', responses={304: {'description': 'Prices unchanged'}})
    async def prices(if_none_match: str | None = Header(default=None)):
        """Configured answer prices (US dollars per million tokens) for viewer receipts."""
        return cached_json(*await service.prices(), if_none_match)

    @router.post('/matches/{match_id}/sessions')
    async def start(match_id: str, body: ViewerSessionRequest):
        return await service.start(match_id, body.profile_id, body.viewer_id)

    @router.get(session)
    async def bootstrap(match_id: str, token: UUID):
        return await service.bootstrap(match_id, token)

    @router.put(session + '/audience')
    async def select_audience(match_id: str, token: UUID, body: ViewerAudience):
        return await service.select_audience(match_id, token, body)

    @router.post(session + '/messages')
    async def ask(match_id: str, token: UUID, body: MessageRequest):
        return await service.questions.ask(match_id, token, body.request_id, body.prompt, body.seq)

    @router.delete(session + '/messages')
    async def clear_questions(match_id: str, token: UUID):
        return await service.clear_questions(match_id, token)

    @router.get(session + '/turns/{turn_id}/replay/{page}')
    async def replay_page(match_id: str, token: UUID, turn_id: int, page: int):
        return await service.questions.replay_page(match_id, token, turn_id, page)

    @router.post(session + '/offers/{offer_id}/track')
    async def track(match_id: str, token: UUID, offer_id: UUID):
        return await service.track(match_id, token, offer_id)

    @router.delete(session + '/pins/{calculation_id}')
    async def untrack(match_id: str, token: UUID, calculation_id: str):
        return await service.untrack(match_id, token, calculation_id)

    @router.websocket(session + '/live')
    async def live(ws: WebSocket, match_id: str, token: UUID):
        await stream_product(ws, service, match_id, token)

    return router
