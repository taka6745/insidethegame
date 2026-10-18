"""Product transport; shares the established question/session use cases."""
import asyncio
from uuid import UUID

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from backend.domain import RuleError
from .questions import SessionRequest, MessageRequest


async def stream_product(ws, service, token):
    try:
        peer, snapshot = await service.attach(token)
    except RuleError as exc:
        # Accept before closing so browsers receive the application close code
        # rather than an opaque HTTP handshake failure.
        await ws.accept()
        await ws.close(code=4001 if exc.status < 500 else 1013)
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
        service.live.detach(peer)


def product_router(service):
    router = APIRouter(prefix='/product', tags=['Match viewer'])

    @router.post('/demo/reset')
    async def reset_demo():
        return await service.reset_demo()

    @router.get('/profiles')
    async def profiles():
        return await service.profiles()

    @router.post('/sessions')
    async def start(body: SessionRequest):
        return await service.start(body.profile_id)

    @router.get('/{token}')
    async def bootstrap(token: UUID):
        return await service.bootstrap(token)

    @router.post('/{token}/messages')
    async def ask(token: UUID, body: MessageRequest):
        return await service.questions.ask(token, body.request_id, body.prompt)

    @router.post('/{token}/offers/{offer_id}/track')
    async def track(token: UUID, offer_id: UUID):
        return await service.track(token, offer_id)

    @router.delete('/{token}/pins/{calculation_id}')
    async def untrack(token: UUID, calculation_id: str):
        return await service.untrack(token, calculation_id)

    @router.websocket('/{token}/live')
    async def live(ws: WebSocket, token: UUID):
        await stream_product(ws, service, token)

    return router
