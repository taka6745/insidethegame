"""Fixture-backed API with an optional Microsoft Agent Framework custom-stat lab."""
import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

import anyio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .domain import MatchEvent, Narrative, Preferences, RuleError, card_ids, pin
from .fixtures import FixtureFeed
from .store import Store


class StartSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str = Field(min_length=1, max_length=100)


class PinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calculation_id: str = Field(min_length=1, max_length=100)
    replace: str | None = None


@dataclass
class Peer:
    profile_id: str
    token: UUID
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=32))

    def offer(self, message):
        if self.queue.full():
            # A slow client must reconnect for a complete snapshot, never silently lose updates.
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait({"close": 1013})
        else:
            self.queue.put_nowait(message)


def create_app(store=None, feed=None, *, match_id="synthetic-demo", slots=3, enable_dev_feed=False, lab=None):
    if not 1 <= slots <= 4:
        raise ValueError("Fixture harness supports 1–4 cards; production card count is still undecided")
    store = store or Store(os.environ["ACCOUNTS_DATABASE_URL"], os.environ["MATCH_APP_DATABASE_URL"])
    feed = feed or FixtureFeed(match_id, slots)
    peers = {}
    sessions_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.initialize)
        if lab:
            await lab.initialize()
        try:
            yield
        finally:
            if lab:
                await lab.close()

    app = FastAPI(title="Inside the Game — user backend harness", lifespan=lifespan)
    app.state.store, app.state.feed = store, feed
    if lab:
        from .routes.lab import lab_router
        app.include_router(lab_router(lab))
        app.state.lab = lab

    @app.exception_handler(RuleError)
    async def rule_error(request, exc):
        return JSONResponse({"code": exc.code, "detail": exc.message}, status_code=exc.status)

    async def snapshot(token):
        row = await asyncio.to_thread(store.read, token, match_id)
        state = row["state"]
        bucket = f"{state['team']}:{state['fan_style']}"
        view = await asyncio.to_thread(feed.view, bucket, state["team"], state["pins"])
        cards = [{"kind": kind, "id": key, "value": view["values"][kind][key]}
                 for kind, key in card_ids(view["defaults"], state["pins"], slots)]
        return {"mode": "fixture", "synthetic": True, "match_id": match_id,
                "profile_id": row["profile_id"], "bucket": bucket, "cards": cards,
                "pins": state["pins"], "narratives": view["narratives"], "key_moments": view["key_moments"]}

    async def notify(token, reason):
        if peer := peers.get(token):
            try:
                peer.offer({"type": "snapshot", "reason": reason, "data": await snapshot(token)})
            except RuleError as exc:
                peer.offer({"close": 4001} if exc.code == "session_replaced" else
                           {"type": "error", "code": exc.code, "detail": exc.message})

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": "fixture", "synthetic": True}

    @app.get("/ready")
    async def ready():
        await asyncio.to_thread(store.ready)
        return {"status": "ready", "mode": "fixture"}

    @app.get("/profiles")
    async def profiles():
        return {"profiles": await asyncio.to_thread(store.profiles), "mode": "fixture"}

    @app.post("/sessions", status_code=201)
    async def start(body: StartSession):
        async with sessions_lock:
            row = await asyncio.to_thread(store.start, match_id, body.profile_id)
            for peer in list(peers.values()):
                if peer.profile_id == body.profile_id:
                    peer.offer({"close": 4001})
            return {"session_token": str(row["token"]), "snapshot": await snapshot(row["token"])}

    @app.get("/sessions/{token}")
    async def get_session(token: UUID):
        return await snapshot(token)

    @app.patch("/sessions/{token}/preferences")
    async def preferences(token: UUID, body: Preferences):
        await asyncio.to_thread(store.change, token, match_id, lambda state: state.update(body.model_dump()))
        await notify(token, "preferences_changed")
        return await snapshot(token)

    @app.get("/calculations")
    async def calculations():
        return {"mode": "fixture", "match_id": match_id, "calculations": feed.calculations}

    @app.post("/sessions/{token}/pins")
    async def add_pin(token: UUID, body: PinRequest):
        feed.calculation(body.calculation_id)

        def update(state):
            state["pins"] = pin(state["pins"], body.calculation_id, slots, body.replace)

        await asyncio.to_thread(store.change, token, match_id, update)
        await notify(token, "pins_changed")
        return await snapshot(token)

    @app.delete("/sessions/{token}/pins/{calculation_id}")
    async def remove_pin(token: UUID, calculation_id: str):
        def update(state):
            if calculation_id not in state["pins"]:
                raise RuleError("pin_not_found", "This statistic is not pinned", 404)
            state["pins"].remove(calculation_id)

        await asyncio.to_thread(store.change, token, match_id, update)
        await notify(token, "pins_changed")
        return await snapshot(token)

    @app.websocket("/sessions/{token}/live")
    async def live(ws: WebSocket, token: UUID):
        async with sessions_lock:
            try:
                initial = await snapshot(token)
            except RuleError:
                await ws.close(code=4001)
                return
            await ws.accept()
            if old := peers.get(token):
                old.offer({"close": 4001})
            peer = Peer(initial["profile_id"], token)
            peers[token] = peer
            await ws.send_json({"type": "snapshot", "data": initial})

        async def send():
            while True:
                message = await peer.queue.get()
                if "close" in message:
                    await ws.close(code=message["close"])
                    return
                await ws.send_json(message)

        async def receive():
            while True:
                message = await ws.receive_json()
                if message == {"type": "ping"}:
                    peer.offer({"type": "pong"})

        try:
            # Structured cancellation keeps send/receive inside the socket lifetime.
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
            if peers.get(token) is peer:
                peers.pop(token)

    if enable_dev_feed:
        @app.post("/dev/events", status_code=202)
        async def inject_event(event: MatchEvent):
            changed = feed.accept_event(event)
            if changed:
                for token in list(peers):
                    await notify(token, "match_event")
            return {"accepted": True, "duplicate": not changed, "mode": "fixture"}

        @app.post("/dev/narratives", status_code=202)
        async def inject(narrative: Narrative):
            feed.accept(narrative)
            for token, peer in list(peers.items()):
                try:
                    current = await snapshot(token)
                except RuleError:
                    peer.offer({"close": 4001})
                    continue
                if current["bucket"] == narrative.bucket:
                    peer.offer({"type": "narrative", "data": narrative.model_dump(), "synthetic": True})
                    peer.offer({"type": "snapshot", "reason": "narrative_received", "data": current})
            return {"accepted": True, "mode": "fixture"}

    return app


def from_env():
    if os.environ.get("BACKEND_MODE") != "fixture":
        raise RuntimeError("Only BACKEND_MODE=fixture is implemented; real adapters are not configured")
    from .upstream import FixtureServices
    match_id = os.environ.get("MATCH_ID", "synthetic-demo")
    slots = int(os.environ.get("CARD_SLOTS", "3"))
    feed = FixtureServices(match_id, slots, os.environ["ETL_GRAPHQL_URL"], os.environ["NARRATIVE_GRAPHQL_URL"])
    store = Store(os.environ["ACCOUNTS_DATABASE_URL"], os.environ["MATCH_APP_DATABASE_URL"])
    lab = None
    if os.environ.get("ENABLE_FILTER_LAB") == "1":
        from .lab_factory import create_filter_lab
        lab = create_filter_lab(store)
    return create_app(store=store, feed=feed, match_id=match_id, slots=slots, lab=lab,
                      enable_dev_feed=os.environ.get("ENABLE_DEV_FEED") == "1")
