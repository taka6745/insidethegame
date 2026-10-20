"""The engine as a service: Service Bus in, Cosmos DB state, Service Bus out, GraphQL history.

    python -m narrative_engine.service      # settings from the environment or .env

| Setting | Meaning |
| --- | --- |
| ETL_GRAPHQL_URL | ETL Data API builder GraphQL endpoint |
| SERVICEBUS_NOTIFICATIONS | listen connection string for match-notifications (ETL output) |
| SERVICEBUS_PRESENCE | listen connection string for the presence topic (optional) |
| SERVICEBUS_NARRATIVES | send connection string for the narratives topic |
| COSMOS_ENDPOINT | Cosmos DB account (Entra ID auth); unset = in-memory store |
| AGENTS | `llm` (default; OPENAI_* settings) or `fake` |
| MATCH_IDS | optional comma-separated matchIds to handle; others are completed and ignored |
| PORT | GraphQL port (default 8000) |
| APPLICATIONINSIGHTS_CONNECTION_STRING | optional: Agent Framework traces (agent runs, model calls, tokens) and logs to Application Insights; ENABLE_SENSITIVE_DATA=true adds prompts and replies |
"""
import asyncio
import logging
import os

from narrative_engine.core.config import Settings
from narrative_engine.core.models import parse_notification
from narrative_engine.core.orchestrator import MatchOrchestrator

log = logging.getLogger("narrative_engine")


class Router:
    """One orchestrator per match, created on its first message."""

    def __init__(self, data, agents, store, publisher, settings=Settings(), match_ids=None):
        self.data, self.agents, self.store, self.publisher = data, agents, store, publisher
        self.settings, self.match_ids = settings, match_ids
        self.engines = {}

    def engine(self, match_id):
        if match_id not in self.engines:
            self.engines[match_id] = MatchOrchestrator(match_id, self.data, self.agents, self.store, self.publisher,
                                                       self.settings)
        return self.engines[match_id]

    def wanted(self, match_id):
        return not self.match_ids or match_id in self.match_ids

    async def handle(self, body, message_type=None):
        """Record one notification; its match's worker does the slow work in the background."""
        message = parse_notification(body, message_type)
        if message is None or not self.wanted(message.matchId):
            return
        log.info("%s %s", message.matchId, type(message).__name__)
        await self.engine(message.matchId).accept(message)

    async def idle(self):
        """Wait until every match's worker has finished (tests)."""
        while workers := [e.worker for e in self.engines.values() if e.worker and not e.worker.done()]:
            await asyncio.gather(*workers)

    async def resume(self):
        """Restart the workers of live matches, which may have work left from before a restart."""
        for match_id in await self.store.live_match_ids():
            if self.wanted(match_id):
                self.engine(match_id).kick()


def configure_telemetry():
    """Agent Framework emits OpenTelemetry spans for every agent run and model call (latency, model,
    tokens); Azure Monitor exports them, with the logs, when a connection string is set."""
    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    from agent_framework.observability import enable_instrumentation
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(logger_name="narrative_engine")
    enable_instrumentation()
    log.info("telemetry to Application Insights")


async def serve():
    import uvicorn

    from narrative_engine.agents.fake import FakeAgents
    from narrative_engine.agents.llm import LLMAgents, LLMSettings, load_env
    from narrative_engine.api import NarrativeApi
    from narrative_engine.match_data.etl_graphql import GraphQLMatchData
    from narrative_engine.store.cosmos import CosmosStore
    from narrative_engine.store.memory import MemoryStore
    from narrative_engine.transport.servicebus import ServiceBusPublisher, SubscriptionListener

    load_env()
    configure_telemetry()
    env = os.environ
    data = GraphQLMatchData(env["ETL_GRAPHQL_URL"])
    agents = FakeAgents() if env.get("AGENTS") == "fake" else LLMAgents(LLMSettings.from_env())
    store = CosmosStore(env["COSMOS_ENDPOINT"]) if env.get("COSMOS_ENDPOINT") else MemoryStore()
    publisher = ServiceBusPublisher(env["SERVICEBUS_NARRATIVES"])
    match_ids = {m.strip() for m in env.get("MATCH_IDS", "").split(",") if m.strip()} or None
    router = Router(data, agents, store, publisher, match_ids=match_ids)

    tasks = [SubscriptionListener(env["SERVICEBUS_NOTIFICATIONS"], "match-notifications", "narrative-engine",
                                  router.handle).run()]
    if env.get("SERVICEBUS_PRESENCE"):
        tasks.append(SubscriptionListener(env["SERVICEBUS_PRESENCE"], "presence", "narrative-engine", router.handle,
                                          fixed_type="PresenceChanged").run())
    port = int(env.get("PORT", 8000))
    server = uvicorn.Server(uvicorn.Config(NarrativeApi(store), host="0.0.0.0", port=port, log_level="warning"))
    tasks.append(server.serve())
    log.info("store=%s agents=%s matches=%s graphql=:%s", type(store).__name__, type(agents).__name__,
             sorted(match_ids) if match_ids else "all", port)
    try:
        await router.resume()
        await asyncio.gather(*tasks)
    finally:
        await publisher.aclose()
        await data.aclose()
        if hasattr(agents, "aclose"):
            await agents.aclose()
        if hasattr(store, "aclose"):
            await store.aclose()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
