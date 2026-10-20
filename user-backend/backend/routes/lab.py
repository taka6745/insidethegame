"""Lab HTTP boundary: validate inputs, call services, return results."""
from urllib.parse import quote, unquote

from fastapi import APIRouter, Request, Response
from backend.domain import RuleError
from backend.models.recording import MAX_RECORDING_BYTES
from backend.models.lab import AddCalculation, PlanRequest, StartReplay


def lab_router(service):
    router = APIRouter(prefix="/lab", tags=["Development filter lab"])

    @router.get("/scenario")
    async def scenario():
        return service.scenario()

    @router.get("/state")
    async def state():
        return await service.state()

    @router.get("/recording")
    async def recording():
        filename, content = await service.recording()
        return Response(content, media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe="")})

    @router.get("/events/{delivery_index}")
    async def event_record(delivery_index: int):
        return await service.event_record(delivery_index)

    @router.post("/recording")
    async def load_recording(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_RECORDING_BYTES:
                raise RuleError("recording_too_large", "Recording must be no larger than 2 MiB", 413)
        filename = unquote(request.headers.get("X-Recording-Filename", "recording.json"))
        return await service.load_recording(bytes(content), filename)

    @router.post("/recording/default")
    async def default_recording():
        return await service.load_recording()

    @router.post("/calculations", status_code=201)
    async def register(body: AddCalculation):
        return await service.register(body.rule, body.label)

    @router.post("/plan")
    async def plan(body: PlanRequest):
        return await service.plan(body.prompt, body.conversation_id)

    @router.post("/replay/start")
    async def start(body: StartReplay):
        return await service.start(body.interval_ms)

    @router.post("/reset")
    async def reset():
        return await service.reset()

    return router
