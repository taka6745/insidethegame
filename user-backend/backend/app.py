"""Fixture-backed API with an optional Microsoft Agent Framework custom-stat lab."""
import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .domain import RuleError
from .fixtures import FixtureFeed
from .store import Store
from .repositories.audiences import AudienceRepository
from .services.audiences import AudienceService
from .routes.audiences import audience_router

from .services.viewers import ViewerService
from .routes.viewers import viewer_router


def create_app(store=None, feed=None, *, match_id="synthetic-demo", slots=3, enable_dev_feed=False, lab=None, narrative_connection=None, questions=None, enable_product=False):
    if enable_product and lab and questions and narrative_connection:
        raise ValueError("Service Bus ingress currently serves only the legacy viewer harness; "
                         "the product demo requires its GraphQL checkpoint adapter")
    if not 1 <= slots <= 4:
        raise ValueError("Fixture harness supports 1–4 cards; production card count is still undecided")
    store = store or Store(os.environ["ACCOUNTS_DATABASE_URL"], os.environ["MATCH_APP_DATABASE_URL"])
    feed = feed or FixtureFeed(match_id, slots)
    audiences = AudienceService(AudienceRepository(store), match_id)
    viewers = ViewerService(store, feed, match_id, slots)
    product = None
    if enable_product and questions and lab:
        from .services.product import ProductService
        product = ProductService(questions, lab, audiences)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.initialize)
        await audiences.initialize()
        if lab:
            await lab.initialize()
        if questions:
            await questions.initialize()
        if product:
            await product.initialize()
        consumer_task = None
        if narrative_connection:
            from .adapters.narratives import NarrativeBusConsumer
            consumer = NarrativeBusConsumer(narrative_connection, viewers.deliver_narrative)
            consumer_task = asyncio.create_task(consumer.run())
        try:
            yield
        finally:
            if consumer_task:
                consumer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await consumer_task
            if product:
                await product.close()
            if lab:
                await lab.close()

    app = FastAPI(title="Inside the Game — user backend harness", lifespan=lifespan)
    app.state.store, app.state.feed = store, feed
    app.state.viewers = viewers
    app.include_router(viewer_router(viewers, enable_dev_feed=enable_dev_feed))
    app.include_router(audience_router(audiences, enable_dev_feed=enable_dev_feed))
    if product:
        from .routes.product import product_router
        app.include_router(product_router(product))
        app.state.product = product
    if questions:
        from .routes.questions import question_router
        app.include_router(question_router(questions))
        app.state.questions = questions
    if lab:
        from .routes.lab import lab_router
        app.include_router(lab_router(lab))
        app.state.lab = lab

    @app.exception_handler(RuleError)
    async def rule_error(request, exc):
        return JSONResponse({"code": exc.code, "detail": exc.message}, status_code=exc.status)

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": "fixture", "synthetic": True}

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
    questions = None
    if lab:
        from .question_factory import create_question_service
        questions = create_question_service(store, lab)
    return create_app(store=store, feed=feed, match_id=match_id, slots=slots, lab=lab, questions=questions, enable_product=True,
                      narrative_connection=os.getenv("NARRATIVE_SERVICEBUS_CONNECTION_STRING"),
                      enable_dev_feed=os.environ.get("ENABLE_DEV_FEED") == "1")
