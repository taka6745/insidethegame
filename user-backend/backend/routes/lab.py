"""Lab HTTP boundary: validate inputs, call services, return results."""
from fastapi import APIRouter
from backend.models.lab import AddCalculation, PlanRequest, StartReplay


def lab_router(service):
    router = APIRouter(prefix="/lab", tags=["Development filter lab"])

    @router.get("/scenario")
    async def scenario():
        return service.scenario()

    @router.get("/state")
    async def state():
        return await service.state()

    @router.post("/calculations", status_code=201)
    async def register(body: AddCalculation):
        return await service.register(body.rule, body.label)

    @router.post("/plan")
    async def plan(body: PlanRequest):
        return await service.plan(body.prompt)

    @router.post("/replay/start")
    async def start(body: StartReplay):
        return await service.start(body.interval_ms)

    @router.post("/reset")
    async def reset():
        return await service.reset()

    return router
