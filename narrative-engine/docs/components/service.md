# Service

> **In short:** the deployed process. It reads settings, builds the store, agents, ETL client and Service Bus adapters, routes each message to its match's orchestrator, resumes unfinished matches after a restart and serves the history API.

| | |
| --- | --- |
| **Status** | Implemented · tested · deployed |
| **Code** | [`narrative_engine/service.py`](../../narrative_engine/service.py) |
| **Run** | `python -m narrative_engine.service` (the Dockerfile's command) |
| **Depends on** | every other component |
| **Tests** | `tests/test_servicebus.py` (router, settle, publisher) |

## 1. Responsibilities

*In short: wiring and routing; no match logic lives here.*

- Load settings from the environment, or from the ignored `narrative-engine/.env` locally.
- Turn on telemetry when an Application Insights connection string is set.
- Create one `MatchOrchestrator` per match on first sight (`Router.engine`).
- Ignore matches outside `MATCH_IDS` (completed without work), so old ETL backlogs cost nothing.
- Run the two Service Bus listeners and the GraphQL server side by side.
- On start-up, restart the workers of matches the store marks `live` (`Router.resume`).

## 2. Settings

*In short: environment variables; secrets come from Container App secrets in Azure.*

| Variable | Meaning |
| --- | --- |
| `ETL_GRAPHQL_URL` | ETL Data API builder GraphQL endpoint |
| `SERVICEBUS_NOTIFICATIONS` | Listen connection string for `match-notifications` (ETL) |
| `SERVICEBUS_PRESENCE` | Listen connection string for `presence` (optional) |
| `SERVICEBUS_NARRATIVES` | Send connection string for `narratives` |
| `COSMOS_ENDPOINT` | Cosmos DB account (Entra ID auth); unset = in-memory store |
| `AGENTS` | `llm` (default) or `fake` |
| `OPENAI_*` | Model settings per agent; see [agents](agents.md#3-model-settings) |
| `MATCH_IDS` | Optional comma-separated matchIds to handle |
| `PORT` | GraphQL port (default 8000) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional; enables traces and log export |
| `ENABLE_SENSITIVE_DATA` | `true` adds prompts and replies to traces (off by default) |
| `OTEL_SERVICE_NAME` | Name shown in Application Insights (`narrative-engine`) |

## 3. Router

*In short: one orchestrator per match, created lazily.*

| Method | What it does |
| --- | --- |
| `handle(body, messageType)` | Parse the message; if the match is wanted, `accept` it on that match's orchestrator |
| `wanted(matchId)` | `True` when `MATCH_IDS` is empty or contains the match |
| `resume()` | Kick the workers of every live match in the store |
| `idle()` | Wait until every worker is idle (tests) |

## 4. Telemetry

*In short: Agent Framework spans and the engine's own logs go to Application Insights.*

`configure_telemetry()` calls Azure Monitor's `configure_azure_monitor(logger_name="narrative_engine")` and Agent Framework's `enable_instrumentation()`. Each agent run becomes an `invoke_agent <name>` span with a nested `chat <model>` span carrying latency and token counts. Cosmos, Service Bus and HTTP calls are traced too. How to view it: [deployment.md](../deployment.md#4-monitoring).
