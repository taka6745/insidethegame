"""Replaceable composition root; no imports from user-backend."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .adapters.upstreams import AudienceCatalog, EtlSnapshots
from .repositories.snapshots import SnapshotRepository
from .routes.api import routes
from .services.commentary import CommentaryFixture
from .services.narratives import NarrativeService


def create_app(service):
    @asynccontextmanager
    async def lifespan(app):
        yield
        service.repository.close()

    app = FastAPI(title='Recorded-match narrative demo stub', lifespan=lifespan)
    app.include_router(routes(service))
    return app


def from_env():
    repository = SnapshotRepository(os.getenv('NARRATIVE_DATABASE_PATH', '/data/narrative.sqlite3'))
    return create_app(NarrativeService(repository,
        EtlSnapshots(os.getenv('ETL_BASE_URL', 'http://demo-etl:8000')),
        AudienceCatalog(os.getenv('AUDIENCE_BASE_URL', 'http://backend:8000')),
        CommentaryFixture(os.getenv('NARRATIVE_FIXTURE_PATH', '/app/fixtures/grf-narratives.json'))))
