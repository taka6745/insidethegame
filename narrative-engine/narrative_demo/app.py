"""Replaceable composition root; no imports from user-backend."""
import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from .adapters.upstreams import AudienceCatalog, EtlSnapshots
from .repositories.snapshots import SnapshotRepository
from .routes.api import routes
from .services.commentary import CommentaryFixture
from .services.narratives import NarrativeService


def create_app(service, broker=None):
    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(broker.run()) if broker else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            service.repository.close()

    app = FastAPI(title='Recorded-match narrative demo stub', lifespan=lifespan)
    app.include_router(routes(service, broker_enabled=broker is not None))
    return app


def from_env():
    repository = SnapshotRepository(os.getenv('NARRATIVE_DATABASE_PATH', '/data/narrative.sqlite3'))
    service = NarrativeService(repository,
        EtlSnapshots(os.getenv('ETL_BASE_URL', 'http://demo-etl:8000')),
        AudienceCatalog(os.getenv('AUDIENCE_BASE_URL', 'http://backend:8000')),
        CommentaryFixture(os.getenv('NARRATIVE_FIXTURE_PATH', '/app/fixtures/grf-narratives.json')))
    broker = None
    connection = os.getenv('SNAPSHOT_SERVICEBUS_CONNECTION_STRING', '')
    if connection:
        from .adapters.service_bus import NarrativeBroker
        broker = NarrativeBroker(service, connection,
            os.getenv('NARRATIVE_SERVICEBUS_CONNECTION_STRING') or connection,
            input_topic=os.getenv('SNAPSHOT_SERVICEBUS_TOPIC', 'match-notifications'),
            subscription=os.getenv('SNAPSHOT_SERVICEBUS_SUBSCRIPTION', 'narrative-engine'),
            output_topic=os.getenv('NARRATIVE_SERVICEBUS_TOPIC', 'narratives'))
    return create_app(service, broker)
