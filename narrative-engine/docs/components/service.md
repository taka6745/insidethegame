# Service

> **In short:** the deployed process. It reads settings, builds the store, agents, ETL client and Service Bus adapters, routes each message to its match's orchestrator (any number of concurrent matches, one model gate), purges matches with tombstones, resumes unfinished matches after a restart, reconnects to Service Bus in-process and serves the history API.

| | |
| --- | --- |
| **Status** | Implemented · tested |
| **Code** | [`narrative_engine/service.py`](../../narrative_engine/service.py) |
| **Run** | `python -m narrative_engine.service` (the Dockerfile's command) |
| **Depends on** | every other component |
| **Tests** | `tests/test_servicebus.py` (router: concurrent matches, model limit, purge and restart, health; settle, publisher; seed routes: [demo](demo.md)) |

## 1. Responsibilities

*In short: wiring and routing; no match logic lives here.*

- Load settings from the environment, or from the ignored `narrative-engine/.env` locally.
- Turn on telemetry when an Application Insights connection string is set.
- Create one `MatchOrchestrator` per matchId on first sight (`Router.engine`); all share one `ModelGate`.
- Lifecycle per matchId: it starts with its first notification, ends with its final period (MA1 `capabilities.periods`, else `FINAL_PERIOD`) or a purge. Tombstoned matches, and matches whose MA1 predates the purge-all cut-off, are completed without work.
- Run the Service Bus listener, the target poll and the GraphQL server side by side.
- On start-up, load the tombstones, then restart the workers of matches the store marks `live` (`Router.start`).
- `GET /health`: `200 {"status": "ok"}`, or `503 {"status": "unhealthy", "problems": [...]}` while the user backend's prompts are unreachable or invalid. There is no fallback to fixed buckets or shipped prompts: authoring waits.

## 2. Settings

*In short: environment variables; secrets come from Container App secrets in Azure.*

| Variable | Meaning |
| --- | --- |
| `ETL_GRAPHQL_URL` | ETL Data API builder GraphQL endpoint |
| `SERVICEBUS_NOTIFICATIONS` | Listen connection string for `match-notifications` (ETL) |
| `NOTIFICATIONS_SUBSCRIPTION` | Its subscription (default `narrative-engine`; local stack `narrative-live`) |
| `USER_BACKEND_URL` | Required: audience targets and followed topics (per matchId), prompts and the storyline policy |
| `DECISION_*` | Required: the decision model ([decisions](decisions.md)); Microsoft-Decision-1 when `DECISION_BASE_URL` is set, else the constrained-LLM fallback on the agents' model |
| `MODEL_CONCURRENCY`, `AUTHOR_CONCURRENCY`, `FALLBACK_MINUTES`, `FINAL_PERIOD`, `TARGETS_POLL_SECONDS`, `BACKEND_CACHE_SECONDS`, `RETRY_SECONDS`, `RETRY_MAX_SECONDS`, `LAST_N_NARRATIVES` | [Settings](core.md#2-settings-configpy) (local stack: `NARRATIVE_MODEL_CONCURRENCY`) |
| `SERVICEBUS_NARRATIVES` | Send connection string for `narratives` |
| `COSMOS_ENDPOINT` | Required: Cosmos DB account (Entra ID auth) |
| `COSMOS_KEY` | Key auth for the local emulator; the store then creates its database and containers |
| `OPENAI_*`, `LOCAL_LLM_*` | Required: model settings per agent (Azure AI Foundry in Azure), falling back to the local model's settings; see [agents](agents.md#3-model-settings). Without them the service fails at start-up. Fake agents and the memory store are for tests and devtools only |
| `PORT` | GraphQL port (default 8000); also `GET /health` and the internal `POST /admin/matches/purge` |
| `ADMIN_TOKEN` | Optional (set on Azure): the purge (and, with `DEMO_SEEDS`, export and restore) then needs `Authorization: Bearer <token>` |
| `DEMO_SEEDS` | `1` mounts the [demo seed adapter](demo.md); local compose and the Azure demo build (`demo_seeds`) set it, a production release (`./dev azure up --release`) leaves it off |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional; enables traces and log export |
| `ENABLE_SENSITIVE_DATA` | `true` adds prompts and replies to traces (off by default) |
| `OTEL_SERVICE_NAME` | Name shown in Application Insights (`narrative-engine`) |

## 3. Router

*In short: one orchestrator per match, created lazily; tombstones keep purged matches out.*

| Method | What it does |
| --- | --- |
| `handle(body, messageType)` | Parse the message; drop it if the match is tombstoned or `admit` refuses it; else `accept` it on the match's orchestrator |
| `admit(message)` | For a match not seen since start-up: refuse (and tombstone) it if its MA1 `timeStamp` (or, with no MA1 in the ETL, the notification's time) is before the purge-all cut-off |
| `purge(matchId)` / `purge(everything=True)` | `POST /admin/matches/purge` ([contract](../../../local/contracts/README.md#5-purge)): write tombstones (and, for `all`, the cut-off) first, then stop the workers and delete checkpoints, blocks and narratives. Returns `{"match_ids", "purged": {"checkpoints", "contextBlocks", "narratives"}}`. Other matches are untouched |
| `poll_targets()` | Every `TARGETS_POLL_SECONDS`: let go of finished matches, re-read targets for the rest |
| `start()` | Load tombstones and the cut-off, kick the workers of every live match not tombstoned |
| `health()` | The prompt source's problems (empty when healthy) |
| `idle()` | Wait until every worker is idle (tests) |

`ModelGate` (`core/gate.py`) caps model calls across all matches at `MODEL_CONCURRENCY`. Waiting calls go summaries first (minute summaries and compressions), then the match served least recently, then arrival order, so every match's context keeps advancing. How many matches one limit sustains: [architecture §6](../architecture.md#6-guarantees-and-limits).

## 4. Telemetry

*In short: Agent Framework spans and the engine's own logs go to Application Insights.*

`configure_telemetry()` calls Azure Monitor's `configure_azure_monitor(logger_name="narrative_engine")` and Agent Framework's `enable_instrumentation()` (sensitive data only with `ENABLE_SENSITIVE_DATA=true`). Each agent run becomes an `invoke_agent <name>` span with a nested `chat <model>` span carrying latency and token counts. Cosmos, Service Bus and HTTP calls are traced too. How to view it: [deployment.md](../deployment.md#4-monitoring).
