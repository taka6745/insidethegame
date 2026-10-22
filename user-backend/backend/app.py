"""Composition root: the multi-match user backend. Swap adapters here, not in services."""
import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .adapters.engine_history import EngineHistoryData
from .adapters.match_data import EtlDabMatchData
from .agents.subscription_planner import SubscriptionPlanner
from .domain import RuleError
from .repositories.audiences import AudienceRepository
from .repositories.config import ConfigRepository
from .repositories.engine_narratives import EngineNarratives
from .repositories.matches import MatchRepository
from .repositories.profiles import ProfileRepository
from .repositories.prompts import PromptRepository
from .repositories.questions import QuestionRepository
from .repositories.subscriptions import SubscriptionRepository
from .routes.admin import admin_router
from .routes.audiences import audience_router
from .routes.product import product_router
from .routes.config import policy_router
from .routes.prompts import prompt_router
from .routes.subscriptions import subscription_router
from .services.audiences import AudienceService
from .services.config import ConfigService
from .services.cross_match import CrossMatch
from .services.match_registry import MatchRegistry
from .services.product import ProductService
from .services.prompts import PromptService
from .services.questions import QuestionService
from .services.subscriptions import SubscriptionService
from .services.replay import ReplayBuilder
from .store import Store


def create_app(store, dab, *, narratives=None, narrative_url=None, narrative_transport=None, agent=None, planner=None,
               follow_model=None, media=None, decide=None,
               streams=(), enable_dev_feed=False, enable_lab=False, enable_demo_seeds=False, upstream_health=None,
               max_calculations=10_000, question_timeout=90, max_active=4):
    """dab: ETL GraphQL (adapters/etl_dab.EtlDab). narratives: the narrative history port, else
    the engine's GraphQL at narrative_url. agent/planner: None when no model is configured, so
    questions and custom-stat plans are refused and /ready reports not ready. follow_model: the follow chat's JSON
    model (adapters/llm.JsonModel), None to refuse the chat (suggestions still work). decide: the yes/no decision
    model for "Follow this story?" offers (adapters/decision), None for no offers. streams: callables
    (registry, product) -> coroutine that consume the brokers."""
    registry = MatchRegistry(MatchRepository(store), max_calculations=max_calculations, dab=dab)
    config = ConfigService(ConfigRepository(store))
    match_data = EtlDabMatchData(dab, registry)
    narratives = narratives or EngineHistoryData(narrative_url, match_data, config, transport=narrative_transport)
    audiences = AudienceService(AudienceRepository(store), registry)
    prompts = PromptService(PromptRepository(store))
    cross = CrossMatch(registry, match_data, config)
    questions = QuestionService(QuestionRepository(store), registry, match_data, narratives, agent, planner, config,
                                timeout=question_timeout, max_active=max_active, replays=ReplayBuilder(media),
                                cross=cross, decide=decide)
    follows = SubscriptionRepository(store)
    product = ProductService(questions, registry, audiences, EngineNarratives(store), config, match_data, dab, media,
                             subscriptions=follows)
    subscriptions = SubscriptionService(follows, questions, registry, match_data, narratives, config, product,
                                        SubscriptionPlanner(follow_model, prompts) if follow_model else None, cross)
    registry.on_purge.append(lambda ids: asyncio.sleep(0, audiences.forget(ids)))

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.initialize)
        await config.initialize()
        await prompts.initialize()
        await questions.initialize()
        await registry.initialize()
        tasks = [asyncio.create_task(stream(registry, product)) for stream in streams]
        tasks.append(asyncio.create_task(registry.watch_gaps(dab.canonical_event, config)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await product.close()
            if hasattr(dab, 'aclose'):
                await dab.aclose()

    app = FastAPI(title='Inside the Game — user backend', lifespan=lifespan)
    app.state.store, app.state.registry, app.state.product = store, registry, product
    app.state.questions, app.state.config = questions, config
    app.include_router(product_router(product))
    app.include_router(subscription_router(subscriptions))
    app.include_router(audience_router(audiences, enable_dev_feed=enable_dev_feed))
    app.include_router(prompt_router(prompts, enable_dev_feed=enable_dev_feed))
    app.include_router(policy_router(config))
    app.include_router(admin_router(registry))
    if enable_demo_seeds:  # demo-only adapter (PLAN.md §10.6); a production release leaves DEMO_SEEDS off
        from .demo.seeds import SeedRepository, demo_seed_router
        app.include_router(demo_seed_router(registry, SeedRepository(store)))
    if enable_dev_feed:
        from .adapters.health import HealthProbe
        from .routes.config import config_router
        from .routes.pipeline import pipeline_router
        from .routes.profiles import profile_router
        from .services.profiles import ProfileService
        app.include_router(config_router(config))
        app.include_router(profile_router(ProfileService(ProfileRepository(store), audiences.repository)))
        app.include_router(pipeline_router(upstream_health and HealthProbe(upstream_health), registry))
    if enable_lab:
        from .routes.lab import lab_router
        from .routes.questions import question_router
        app.include_router(lab_router(registry, planner, product, match_data))
        app.include_router(question_router(questions))

    @app.exception_handler(RuleError)
    async def rule_error(request, exc):
        return JSONResponse({'code': exc.code, 'detail': exc.message}, status_code=exc.status)

    async def readiness():
        checks = {'model': 'configured' if agent is not None and planner is not None else 'missing'}
        try:
            await asyncio.to_thread(store.ready)
            checks['database'] = 'ok'
        except Exception:
            checks['database'] = 'unavailable'
        ready = checks == {'model': 'configured', 'database': 'ok'}
        # A stream gap degrades one match's data, not readiness; it is shown here and on /dev/pipeline.
        return JSONResponse({'status': 'ok' if ready else 'not_ready', 'synthetic': True, 'checks': checks,
                             'matches': len(registry.matches), 'gaps': registry.gaps()}, status_code=200 if ready else 503)

    app.get('/health')(readiness)
    app.get('/ready')(readiness)
    return app


def from_env():
    from .adapters.etl_dab import EtlDab
    from .adapters.hls_media import HlsMedia
    from .adapters.llm import model_configured
    from .adapters.match_reference import data_reference
    from .adapters.match_stream import MatchStream, NarrativeStream
    from .agents.workflow import workflow_from_env

    planner = workflow_from_env(data_reference=data_reference(None))
    from .adapters.decision import yes_no_from_env

    agent = follow_model = None
    if model_configured():
        from .adapters.llm import LocalJsonModel
        from .agents.question import QuestionAgent
        agent = QuestionAgent()
        follow_model = LocalJsonModel.from_env(name='subscription_planner')
    events, narratives = MatchStream.from_env(), NarrativeStream.from_env()
    return create_app(
        Store(os.environ['ACCOUNTS_DATABASE_URL'], os.environ['MATCH_APP_DATABASE_URL']),
        EtlDab(os.environ['ETL_GRAPHQL_URL']), narrative_url=os.environ['NARRATIVE_GRAPHQL_URL'],
        agent=agent, planner=planner, follow_model=follow_model, media=HlsMedia.from_env(),
        decide=yes_no_from_env(follow_model),
        streams=(lambda registry, product: events.run(registry),
                 lambda registry, product: narratives.run(product.narrative)),
        enable_dev_feed=os.environ.get('ENABLE_DEV_FEED') == '1', enable_lab=os.environ.get('ENABLE_FILTER_LAB') == '1',
        enable_demo_seeds=os.environ.get('DEMO_SEEDS') == '1',
        upstream_health={name: url.removesuffix('/graphql') + '/health' for name, url in
                         (('etl', os.environ['ETL_GRAPHQL_URL']), ('narrative', os.environ['NARRATIVE_GRAPHQL_URL']))},
        max_calculations=int(os.getenv('FILTER_MAX_CALCULATIONS', '10000')),
        question_timeout=float(os.getenv('QUESTION_TIMEOUT_SECONDS', '90')),
        max_active=int(os.getenv('QUESTION_MAX_ACTIVE', '4')))
