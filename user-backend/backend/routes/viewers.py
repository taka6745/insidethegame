"""Viewer HTTP/WebSocket transport; state transitions live in ViewerService."""
from uuid import UUID

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from backend.domain import MatchEvent, Narrative, Preferences, RuleError


class StartSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: str = Field(min_length=1, max_length=100)


class PinRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    calculation_id: str = Field(min_length=1, max_length=100)
    replace: str | None = None


async def stream_viewer(ws, service, token):
    try:
        peer, initial = await service.attach(token)
    except RuleError:
        await ws.close(code=4001)
        return
    try:
        await ws.accept()
        await ws.send_json({'type': 'snapshot', 'data': initial})
        async def send():
            while True:
                message = await peer.queue.get()
                if 'close' in message:
                    await ws.close(code=message['close'])
                    return
                await ws.send_json(message)

        async def receive():
            while True:
                if await ws.receive_json() == {'type': 'ping'}:
                    peer.offer({'type': 'pong'})

        async with anyio.create_task_group() as group:
            async def run(operation):
                try:
                    await operation()
                except WebSocketDisconnect:
                    pass
                finally:
                    group.cancel_scope.cancel()
            group.start_soon(run, send)
            await run(receive)
    finally:
        service.live.detach(peer)


def viewer_router(service, *, enable_dev_feed):
    router = APIRouter(tags=['Viewers'])

    @router.get('/ready')
    async def ready():
        return await service.ready()

    @router.get('/profiles')
    async def profiles():
        return await service.profiles()

    @router.post('/sessions', status_code=201)
    async def start(body: StartSession):
        return await service.start(body.profile_id)

    @router.get('/sessions/{token}')
    async def snapshot(token: UUID):
        return await service.snapshot(token)

    @router.patch('/sessions/{token}/preferences')
    async def preferences(token: UUID, body: Preferences):
        return await service.preferences(token, body)

    @router.get('/calculations')
    async def calculations():
        return service.calculations()

    @router.post('/sessions/{token}/pins')
    async def add_pin(token: UUID, body: PinRequest):
        return await service.add_pin(token, body.calculation_id, body.replace)

    @router.delete('/sessions/{token}/pins/{calculation_id}')
    async def remove_pin(token: UUID, calculation_id: str):
        return await service.remove_pin(token, calculation_id)

    @router.websocket('/sessions/{token}/live')
    async def live(ws: WebSocket, token: UUID):
        await stream_viewer(ws, service, token)

    if enable_dev_feed:
        @router.post('/dev/narratives', status_code=202)
        async def narrative(body: Narrative):
            return await service.deliver_narrative(body)

        @router.post('/dev/events', status_code=202)
        async def event(body: MatchEvent):
            return await service.accept_event(body)

    return router
