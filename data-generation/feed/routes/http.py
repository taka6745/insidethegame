"""Provider admin API (dev only, local/contracts/README.md §7) and the HLS origin (§6)."""
import asyncio
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from feed.adapters.hls import LIVE, live_store
from feed.services.feed import MATCH_ID, FeedError

FILE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}")
TYPES = {".m3u8": "application/vnd.apple.mpegurl", ".ts": "video/mp2t", ".m4s": "video/iso.segment",
         ".mp4": "video/mp4", ".aac": "audio/aac"}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture: str = Field(min_length=1, max_length=55)
    kickoff: str = Field(default="next-minute", max_length=40)
    start_seconds: float | None = Field(default=None, description="Dev only: requires FEED_ALLOW_SEEK=1.")
    hold_point: str | None = Field(default=None, max_length=20, description="Seed recording: stop sending here.")
    resume_point: str | None = Field(default=None, max_length=20,
                                     description="Seed recording: wait for the seed's restore, then play on from here.")


class Release(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_seconds: float = Field(default=0.0, ge=0, le=600)


class StartPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]{1,20}$")
    label: str = Field(min_length=1, max_length=40)
    period: int = Field(ge=1, le=5)
    minute: int = Field(ge=0, le=130)
    seed: str | None = Field(default=None, max_length=100)


class SkipTarget(BaseModel):
    """Demo fast-forward target: whole match minutes, or a start point on the main game's clock."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]{1,20}$")
    label: str = Field(min_length=1, max_length=40)
    minutes: int | None = Field(default=None, ge=1, le=120)
    point: str | None = Field(default=None, max_length=20)


class DemoSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixtures: list[str] = Field(min_length=1, max_length=20)
    main_fixture: str | None = Field(default=None, max_length=100)  # None: the first fixture
    stagger_seconds: int = Field(ge=0, le=3600)
    max_active_runs: int = Field(ge=1, le=20)
    start_points: list[StartPoint] = Field(min_length=1, max_length=20)
    skip_targets: list[SkipTarget] | None = Field(default=None, max_length=20)  # None: keep the saved ones
    expected_revision: int


class DemoSkip(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(max_length=20)


class DemoStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point: str | None = Field(default=None, max_length=20)  # None: the first configured start point


class PurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_id: str | None = Field(default=None, max_length=64)
    all: Literal[True] | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.match_id is None) == (self.all is None):
            raise ValueError("Send exactly one of match_id or all: true")
        return self


def router(service, live_root):
    api, live = APIRouter(), live_store(live_root)

    @api.get("/health")
    async def health():
        if not service.ready:
            return JSONResponse({"status": "starting"}, status_code=503)
        return {"status": "ok", "recordings": len(service.streams), "active_runs": service.active_runs()}

    @api.get("/recordings")
    async def recordings():
        return await service.recordings()

    @api.post("/runs", status_code=201)
    async def create_run(body: RunRequest):
        return await service.create_run(body.fixture, body.kickoff, body.start_seconds, body.hold_point,
                                        body.resume_point)

    if service.seeds:  # demo seeds only; a production release leaves DEMO_SEEDS off
        @api.post("/runs/{match_id}/release")
        async def release(match_id: str, body: Release | None = None):
            return await service.release(match_id, (body or Release()).after_seconds)

        @api.post("/demo/skip")
        async def skip_demo(body: DemoSkip):
            return await service.skip_demo(body.target)

    @api.get("/runs")
    async def runs():
        return await service.runs()

    @api.get("/demo")
    async def demo():
        return await service.demo_settings()

    @api.put("/demo")
    async def save_demo(body: DemoSettings):
        settings = body.model_dump(exclude={"expected_revision"})
        if settings["skip_targets"] is not None:
            settings["skip_targets"] = [{k: v for k, v in t.items() if v is not None} for t in settings["skip_targets"]]
        return await service.save_demo_settings(settings, body.expected_revision)

    @api.post("/demo/start")
    async def start_demo(response: Response, body: DemoStart | None = None):
        result = await service.start_demo((body or DemoStart()).point)
        response.status_code = 201 if result["started"] else 200
        return result

    @api.post("/admin/matches/purge")
    async def purge(body: PurgeRequest):
        return await service.purge(body.match_id, everything=bool(body.all))

    @api.get("/hls/{match_id}/{name}")
    async def hls(match_id: str, name: str):
        # Only played segments exist in the run's directory, so serving what is there is safe.
        if not MATCH_ID.fullmatch(match_id) or not FILE.fullmatch(name) or name.endswith(".tmp"):
            raise HTTPException(404)
        suffix = Path(name).suffix
        found = await asyncio.to_thread(live.open, match_id, name) if suffix in TYPES else None
        if found is None:
            raise HTTPException(404)
        headers = {"Cache-Control": "no-cache" if name == LIVE else "public, max-age=31536000, immutable"}
        if isinstance(found, Path):
            return FileResponse(found, media_type=TYPES[suffix], headers=headers)
        return StreamingResponse(found, media_type=TYPES[suffix], headers=headers)  # Blob chunks

    return api


def create_app(service, live_root, lifespan=None):
    app = FastAPI(title="Match feed (simulated provider)", lifespan=lifespan)

    @app.exception_handler(FeedError)
    async def feed_error(_: Request, exc: FeedError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    app.include_router(router(service, live_root))
    return app
