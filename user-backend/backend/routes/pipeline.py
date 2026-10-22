"""Developer pipeline status: this API, its stream gaps, and whichever upstream health URLs are configured."""
import asyncio

from fastapi import APIRouter


def pipeline_router(probe, registry):
    router = APIRouter(prefix='/dev', tags=['Developer status'])

    @router.get('/pipeline')
    async def pipeline():
        upstream = await probe.check() if probe else []
        open_gaps = registry.gaps()
        filled = await asyncio.to_thread(registry.repository.gaps)
        backend = {'name': 'user-backend', 'status': 'degraded' if open_gaps else 'ok'}
        if open_gaps:
            backend['detail'] = f'{len(open_gaps)} match(es) waiting for a missing event'
        return {'services': [backend, *upstream], 'gaps': [*open_gaps, *filled]}

    return router
