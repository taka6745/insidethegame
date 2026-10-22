"""The engine as a service: Service Bus in, Cosmos DB state, Service Bus out, GraphQL history.

    python -m narrative_engine.service      # settings from the environment or .env

| Setting | Meaning |
| --- | --- |
| ETL_GRAPHQL_URL | ETL Data API builder GraphQL endpoint |
| SERVICEBUS_NOTIFICATIONS | listen connection string for match-notifications (ETL output) |
| NOTIFICATIONS_SUBSCRIPTION | its subscription (default narrative-engine; the local stack uses narrative-live) |
| SERVICEBUS_NARRATIVES | send connection string for the narratives topic |
| USER_BACKEND_URL | required: the user backend's audience targets and followed topics (per matchId), prompts and storyline policy. No fallback: while it cannot answer, authoring waits and /health is 503 |
| COSMOS_ENDPOINT | required: Cosmos DB account (Entra ID auth, or COSMOS_KEY for the emulator) |
| OPENAI_*, LOCAL_LLM_* | required: the agents' model settings (agents.llm); fake agents (devtools/, not in the image) and the memory store are for tests and devtools only |
| DECISION_* | required: the decision model (decisions/; Microsoft-Decision-1, or the constrained-LLM fallback when DECISION_BASE_URL is unset): story-follow triggers and the analyst's and authors' claim checks (the storyline policy's `claims`) |
| MODEL_CONCURRENCY, AUTHOR_CONCURRENCY, FALLBACK_MINUTES, FINAL_PERIOD, TARGETS_POLL_SECONDS, ... | `core.config.Settings` |
| PORT | GraphQL port (default 8000); also serves `GET /health` and `POST /admin/matches/purge` |
| ADMIN_TOKEN | optional (set on Azure): the purge then needs `Authorization: Bearer <token>` |
| APPLICATIONINSIGHTS_CONNECTION_STRING | optional: Agent Framework traces (agent runs, model calls, tokens) and logs to Application Insights; ENABLE_SENSITIVE_DATA=true (off by default) adds prompts and replies |

Every matchId gets its own orchestrator on its first notification. A match ends with its final
period (MA1 capabilities.periods) or a purge. Purges write tombstones first (in the store, so they
survive restarts); a tombstoned match's late notifications are dropped, as are those of a match
whose MA1 predates the latest purge-all cut-off.
"""
import asyncio
import contextlib
import hmac
import json
import logging
import os
from collections import Counter

from narrative_engine.core.config import Settings
from narrative_engine.core.gate import ModelGate
from narrative_engine.core.models import parse_notification, parse_time
from narrative_engine.core.orchestrator import MatchOrchestrator, utcnow

log = logging.getLogger("narrative_engine")


STORES = ("checkpoints", "contextBlocks", "narratives", "analyses", "storylines", "subscriptionDecisions",
          "subscriptionNarratives")


def sent_at(message):
    return getattr(message, "windowEnd", None) or message.eventTime


class Router:
    """One orchestrator per match, created on its first message; one model gate for all of them."""

    def __init__(self, data, agents, store, publisher, settings=Settings(), targets=None, prompts=None, now=utcnow,
                 policy=None, follows=None, decisions=None):
        self.data, self.agents, self.store, self.publisher = data, agents, store, publisher
        if targets is None:
            raise ValueError("targets are required: the service passes the user backend's")
        self.settings, self.targets, self.prompts, self.now, self.policy = settings, targets, prompts, now, policy
        self.follows, self.decisions = follows, decisions
        self.gate = ModelGate(settings.model_concurrency)
        self.engines = {}
        self.purged, self.cutoff = set(), None  # loaded from the store by `start`

    async def start(self):
        """Load the tombstones, then restart the workers of live matches (work left from before a restart)."""
        self.purged, self.cutoff = await self.store.tombstones()
        for match_id in await self.store.live_match_ids():
            if match_id not in self.purged:
                self.engine(match_id).kick()

    def engine(self, match_id):
        if match_id not in self.engines:
            self.engines[match_id] = MatchOrchestrator(match_id, self.data, self.agents, self.store, self.publisher,
                                                       self.settings, targets=self.targets, prompts=self.prompts,
                                                       gate=self.gate, policy=self.policy, follows=self.follows,
                                                       decisions=self.decisions)
        return self.engines[match_id]

    async def admit(self, message):
        """A match this process has not seen: dropped (and tombstoned) if it predates the purge-all cut-off."""
        if self.cutoff is None:
            return True
        try:
            info = await self.data.match_info(message.matchId)
            stamp = parse_time(info.timeStamp) if info.timeStamp else sent_at(message)
        except LookupError:  # no MA1 in the ETL: purged there too, or not written yet
            stamp = sent_at(message)
        if stamp >= parse_time(self.cutoff):
            return True
        await self.store.add_tombstones([message.matchId])
        self.purged.add(message.matchId)
        log.info("%s predates the purge-all cut-off; dropped", message.matchId)
        return False

    async def handle(self, body, message_type=None):
        """Record one notification; its match's worker does the slow work in the background."""
        message = parse_notification(body, message_type)
        if message is None or message.matchId in self.purged:
            return
        if message.matchId not in self.engines and not await self.admit(message):
            return
        if message.matchId in self.purged:  # purged while admitting
            return
        log.info("%s %s", message.matchId, type(message).__name__)
        await self.engine(message.matchId).accept(message)

    async def stop(self, match_id):
        engine = self.engines.pop(match_id, None)
        if engine:
            engine.closed = True
            if engine.worker and not engine.worker.done():
                engine.worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await engine.worker
        self.gate.forget(match_id)
        for source in (self.targets, self.follows):
            if hasattr(source, "forget"):
                source.forget(match_id)

    async def purge(self, match_id=None, everything=False):
        """`POST /admin/matches/purge`: tombstone first, then stop and delete. Other matches keep running."""
        cutoff = None
        if everything:
            cutoff = self.now().isoformat()
            match_ids = sorted(set(self.engines) | set(await self.store.match_ids()))
        else:
            match_ids = [match_id]
        await self.store.add_tombstones(match_ids, cutoff)
        self.purged.update(match_ids)
        if cutoff and (self.cutoff is None or cutoff > self.cutoff):
            self.cutoff = cutoff
        counts = Counter({name: 0 for name in STORES})
        for m in match_ids:
            await self.stop(m)
            counts.update(await self.store.delete_match(m))
        log.info("purged %s", ", ".join(match_ids) or "nothing")
        return {"match_ids": match_ids, "purged": dict(counts)}

    async def idle(self):
        """Wait until every match's worker has finished (tests)."""
        while workers := [e.worker for e in self.engines.values() if e.worker and not e.worker.done()]:
            await asyncio.gather(*workers)

    async def poll_targets(self):
        """Notice newly active buckets between notifications, so catch-ups need not wait a minute;
        let go of finished matches."""
        while True:
            await asyncio.sleep(self.settings.targets_poll_seconds)
            await self.poll_once()

    async def poll_once(self):
        for match_id, engine in list(self.engines.items()):
            if engine.cp and engine.cp["status"] != "live" and not (engine.worker and not engine.worker.done()):
                await self.stop(match_id)  # complete: a late message starts a fresh orchestrator from the checkpoint
                continue
            try:
                await engine.sync_targets()
            except Exception:
                log.exception("%s: target poll failed", match_id)

    async def health(self):
        """Problems that stop authoring (empty when healthy)."""
        found = []
        for source in (self.prompts, self.policy):
            if problems := getattr(source, "problems", None):
                found += await problems()
        return found


def service_app(api, router, admin_token=None):
    """ASGI: `GET /health`, `POST /admin/matches/purge` (local-contract §5), else GraphQL.
    With admin_token the purge needs `Authorization: Bearer <token>` (Azure; ingress is internal too)."""
    expected = f"Bearer {admin_token}".encode() if admin_token else None
    async def respond(send, status, body):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": json.dumps(body).encode()})

    async def app(scope, receive, send):
        path, method = scope.get("path"), scope.get("method")
        if scope["type"] != "http" or path not in ("/health", "/admin/matches/purge"):
            return await api(scope, receive, send)
        if path == "/health" and method == "GET":
            problems = await router.health()
            return await respond(send, 503 if problems else 200,
                                 {"status": "unhealthy", "problems": problems} if problems else {"status": "ok"})
        if path == "/health" or method != "POST":
            return await respond(send, 405, {"detail": "method not allowed"})
        if expected and not hmac.compare_digest(dict(scope["headers"]).get(b"authorization", b""), expected):
            return await respond(send, 401, {"detail": "unauthorized"})
        body, more = b"", True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        try:
            request = json.loads(body or b"{}")
            match_id, everything = request.get("match_id"), request.get("all", False)
        except (ValueError, AttributeError):
            match_id = everything = None
        one = isinstance(match_id, str) and match_id != "" and everything is False
        if not (one or (everything is True and match_id is None)):
            return await respond(send, 422, {"detail": "exactly one of match_id or all: true"})
        try:
            return await respond(send, 200, await router.purge(match_id, everything=everything))
        except Exception:
            log.exception("purge failed")
            return await respond(send, 503, {"detail": "purge failed; retry"})

    return app


async def open_store(env):
    """Cosmos DB only: match state must survive restarts and purges must be durable."""
    from narrative_engine.store.cosmos import CosmosStore
    return await CosmosStore.open(env["COSMOS_ENDPOINT"], key=env.get("COSMOS_KEY"))


def configure_telemetry():
    """Agent Framework emits OpenTelemetry spans for every agent run and model call (latency, model,
    tokens); Azure Monitor exports them, with the logs and metrics, when a connection string is set.
    Prompts and replies are added only with ENABLE_SENSITIVE_DATA=true (off by default)."""
    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    from agent_framework.observability import enable_instrumentation
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(logger_name="narrative_engine")
    enable_instrumentation(enable_sensitive_data=os.environ.get("ENABLE_SENSITIVE_DATA", "").lower() == "true")
    log.info("telemetry to Application Insights")


async def serve():
    import uvicorn

    import httpx

    from narrative_engine.agents.llm import LLMAgents, LLMSettings, load_env
    from narrative_engine.agents.prompt_source import HttpPromptSource
    from narrative_engine.analysis.policy import HttpPolicySource
    from narrative_engine.api import NarrativeApi
    from narrative_engine.audience.targets import HttpTargetSource
    from narrative_engine.decisions import DecisionSettings, from_settings
    from narrative_engine.follows.topics import HttpTopicSource
    from narrative_engine.match_data.etl_graphql import GraphQLMatchData
    from narrative_engine.transport.servicebus import ServiceBusPublisher, SubscriptionListener

    load_env()
    configure_telemetry()
    env = os.environ
    settings = Settings.from_env(env)
    data = GraphQLMatchData(env["ETL_GRAPHQL_URL"])
    agents = LLMAgents(LLMSettings.from_env())  # no model configured: fails here, visibly
    store = await open_store(env)
    publisher = ServiceBusPublisher(env["SERVICEBUS_NARRATIVES"])
    backend = httpx.AsyncClient(timeout=10)
    targets = HttpTargetSource(env["USER_BACKEND_URL"], backend, settings.backend_cache_seconds)
    prompts = HttpPromptSource(env["USER_BACKEND_URL"], backend, settings.backend_cache_seconds)
    policy = HttpPolicySource(env["USER_BACKEND_URL"], backend, settings.backend_cache_seconds)
    follows = HttpTopicSource(env["USER_BACKEND_URL"], backend, settings.backend_cache_seconds)
    decisions = from_settings(DecisionSettings.from_env(env))  # not configured: fails here, visibly
    router = Router(data, agents, store, publisher, settings, targets=targets, prompts=prompts, policy=policy,
                    follows=follows, decisions=decisions)

    tasks = [SubscriptionListener(env["SERVICEBUS_NOTIFICATIONS"], "match-notifications",
                                  env.get("NOTIFICATIONS_SUBSCRIPTION", "narrative-engine"), router.handle).run(),
             router.poll_targets()]
    port = int(env.get("PORT", 8000))
    app = service_app(NarrativeApi(store), router, env.get("ADMIN_TOKEN"))
    if env.get("DEMO_SEEDS") == "1":  # demo-only adapter (PLAN.md §10.6); a production release leaves it off
        from narrative_engine.demo.seeds import seed_app
        app = seed_app(app, router, env.get("ADMIN_TOKEN"))
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
    tasks.append(server.serve())
    log.info("store=%s agents=%s decisions=%s graphql=:%s model concurrency=%s", type(store).__name__,
             type(agents).__name__, type(decisions).__name__, port, settings.model_concurrency)
    try:
        await router.start()
        await asyncio.gather(*tasks)
    finally:
        await publisher.aclose()
        await data.aclose()
        await backend.aclose()
        await decisions.aclose()
        if hasattr(agents, "aclose"):
            await agents.aclose()
        if hasattr(store, "aclose"):
            await store.aclose()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
