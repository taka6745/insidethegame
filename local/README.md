# Local integration

> **In short:** one Docker Compose project (`itg-local`) runs every service, the Microsoft emulators and the demo operator; `./dev` starts and checks it. Tested; the local stand-ins (feed aside) are never deployed.

| | |
| --- | --- |
| **Status** | Tested (D1–D7 end to end, 22 Oct: PLAN.md §10.7) |
| **Demo** | `demo-control` behind `/demo-api/`; seeds in `.local/seeds/`; `DEMO_SEEDS=1` on feed, ETL, engine, backend |
| **Model** | Local model from the ignored `.local/backend-llm.env`; Decision-1 dev deployment from `.local/decision.env` (never print either) |

Run from the repo root using [`../dev`](../dev). [Quick start](../DEVELOPMENT.md) · [Contracts](contracts.md) · [Verified results](verification.md)

First run `./dev doctor`. `./dev up` and `ACCEPT_EULA=Y ./dev up azure` start containers and run their integration checks before reporting success. The full stack needs no extra CLI installation or account login.

## What runs

| Dependency | Local implementation | Host address |
| --- | --- | --- |
| User databases | PostgreSQL 16, `accounts` + `matchapp` | `localhost:15432` |
| Cosmos infrastructure check (base) | Microsoft Cosmos vNext emulator | `http://localhost:18081` |
| Cosmos explorer | Emulator UI | `http://localhost:11234` |
| Match events (`backend` + `azure`) | Microsoft Event Hubs emulator | AMQP `localhost:15672` |
| Notifications and narratives (`backend` + `azure`) | Microsoft Service Bus emulator | AMQP `localhost:15673` |
| Service Bus storage + ETL SQL (`backend` + `azure`) | SQL Server 2022 Developer | `localhost:11433` |
| User backend (`backend` profile) | FastAPI + WebSocket harness | `http://localhost:18000/docs` |
| Feed (`backend` profile) | [Simulated provider](../data-generation/feed/README.md): recordings → Event Hubs + played HLS; dev-only admin API | `http://localhost:18030` |
| ETL pipeline (GraphQL in `azure` + `backend`; stream `backend`) | SQL `insidethegame` + Data API builder 2.1.5 + [local Stream Analytics stand-in](../etl/README.md) | `http://localhost:15001/graphql` |
| Narrative engine (`backend` profile) | `narrative-live`: the narrative engine on the ETL pipeline, Cosmos emulator state, local model (`.local/backend-llm.env`) | `http://localhost:18012/graphql` |
| Match viewer (`backend` profile) | nginx; per-match HLS proxied from the feed; lab `/lab/`, developer config `/dev/`, demo API `/demo-api/` | `http://localhost:18020/` |
| Demo control (`backend` profile) | [`demo_control.py`](demo_control.py) `serve`: Start demo, Cancel, state, status; seeds at `.local/seeds` → `/seeds` | `/demo-api/` only (no host port) |

Inside Docker use service names and native ports: `postgres:5432` (not the feed's), `feed:8000`, `etl-stream:8000`, `etl-dab:5000`, `narrative-live:8000`, `backend:8000`, `cosmos:8081`, `eventhubs:5672`, `servicebus:5672`, `sql:1433`. Example SDK settings are in [settings.py](settings.py); all credentials there are **public local dummy values**, never cloud credentials. Cosmos uses HTTP for local Python development. Host clients must use the mapped ports above.

Running your application directly on your laptop? Copy the relevant values from [connections.env.example](connections.env.example) into that service's ignored `.env`. The file is not automatically loaded; your application's config loader owns that. GraphQL example:

```sh
curl http://localhost:15001/graphql \
  -H 'Content-Type: application/json' \
  --data '{"query":"{ matches(first: 3) { items { matchId status } } }"}'
```

Only loopback ports are published. Existing projects on ports 3000, 5432 and 4566 are untouched. Avoid exposing this unauthenticated demo stack to a network.

## What tests prove

`ACCEPT_EULA=Y ./dev up backend` builds the feed, viewer, backend, ETL pipeline stand-in and narrative engine, starts both messaging emulators, then runs backend tests and the pipeline probes. `./dev test backend` repeats the checks; they never touch running matches. Review the [licences](#licences) first; no account is needed.

```text
feed ─ MA1, MA3, POS, MatchEvent v2 → Event Hubs ─┬→ backend (received events, custom rules)
  └─ played HLS ← nginx /media/hls/{matchId}/      └→ etl-stream → SQL + etl-dab GraphQL → backend, engine
                                                         └→ Service Bus match-notifications (narrative-live)
                         backend ← Service Bus narratives ← narrative engine (audience targets + prompts from backend)
                            ↓
                          viewer
```

`etl-stream` ([etl/local_stream](../etl/docs/components/local-stream.md)) is a local Python stand-in for the Stream Analytics job; Azure dev runs the real job. ETL GraphQL (`etl-dab`) is the backend's only match-data read path: teams, players, watermarks, SPADL actions and the stat catalogue (`executeStatsAtSeq`, 42 kinds × 3 scopes); questions read recaps from the engine's history GraphQL. Nothing pre-written is on the live path; without a configured model the backend is not ready and questions are refused. All local stand-ins are replaceable and not deployed.

The pipeline probe (`broker_check.py`) sends a synthetic match under a fresh `broker-check-…` id through the real SDKs (MA1, MatchEvent v2 with a duplicate, POS), checks ETL GraphQL's match, watermark and stats (one per enabled `statDefinitions` kind and scope, once the SPADL post-processor caught up) and the backend's match list, then purges the probe from every owner and checks nothing is left. `backend_broker_check.py` replays a probe into an isolated backend registry and schema. Neither touches running matches; isolated backend tests use empty broker settings and HTTP doubles. No cloud throughput or distributed ownership is proved by these checks.

`./dev demo start [fixture…]` purges every match from every owner (`POST /admin/matches/purge {"all": true}`: feed, ETL, engine, backend), then starts one feed run per fixture (default `riverton-forgeham`) at the next whole minute, from 00:00; several fixtures run concurrently. `./dev demo purge` only purges. Configuration stays: account profiles, audience templates (with their enabled buckets), prompts, backend config tables (presentation, prices, stream), `statDefinitions` and the recordings catalogue. Event Hubs consumers start at the present (or their checkpoint), never the retained backlog; Service Bus subscriptions are shared, so consumers settle and drop messages of purged matches. Locally the engine reads `match-notifications` through `narrative-live`; the Azure engine's `narrative-engine` subscription exists only in `etl/infra`. The feed mounts one read-only media root, `ITG_MEDIA_ROOT` (default `.local/media`), and finds `{fixture}/hls/match.m3u8` per recording; a fixture without media plays with `video: false`. `./dev` hard-links each packaged `.local/grf-demo-{fixture}-90/hls/` into that root (no copy; delete `.local/media/{fixture}` to relink after regenerating), so nothing else in `.local/` is mounted. The feed has its own Postgres (`feed-postgres`, reachable only on the feed's `provider` network), like an external provider. The feed publishes only played segments at `/hls/{matchId}/live.m3u8`; nginx proxies `/media/hls/{matchId}/` to it and serves nothing else under `/media/`.

`./dev test`: both Postgres databases (read/write; schemas come from backend migrations), Cosmos document write/read/delete. Creates narrative containers if absent.

`./dev test backend` also checks the ETL pipeline's GraphQL entities and peeks the `narrative-live` subscription (only `MinuteClosed`, `KeyEventDetected`, `PeriodStarted`, `PeriodEnded`).

`./dev test azure`: adds a read-only ETL GraphQL query (stat catalogue + matches on the migrated `insidethegame` schema), Event Hubs SDK send/receive, Service Bus topic/subscription send/receive. Uses dedicated integration consumers. `IntegrationProbe` messages may also reach application consumers; ignore that type. Checks are repeatable and fail with a nonzero exit status.

The `azure` profile has no stream processor: nothing writes match data. The backend profile adds the feed and pipeline above; matches come from `./dev demo start`. The local stand-ins (feed aside) are never deployed; `./dev azure up` deploys the real services ([runbook](../terraform/runbook.md)).

## Demo control and seeds

*In short: the judge demo's operator; it sits between the provider and our services and is not a product service (PLAN.md §10.6).*

```text
viewer ─ /demo-api/{start,cancel,state,status} ─▶ demo-control ─┬▶ feed  /demo/start · /runs/{id}/release
                                                                ├▶ ETL, engine, backend  /admin/matches/{purge,export,restore}
                                                                └▶ /seeds/{seed_id}/manifest.json + {owner}/{fixture}.json
```

| Action | What happens | Status |
| --- | --- | --- |
| Start demo (kickoff) | Purge finished matches, start the three fixtures, main game first, staggered | Tested |
| Start demo (20′, HT, 60′, 85′) | Feed creates waiting runs; restore ETL → engine → backend from the seed under the new ids; release main game first; any failure purges (`503`), a stale seed is `409` | Tested (60′/85′ start too slow: PLAN.md §10.7) |
| Cancel demo | Purge every match from every owner, feed first | Tested |
| Status | Seven stages, each from a real check; wakes apps scaled to zero | Tested |
| `record {point} [--from {point}]`, `capture {point}` | Held runs send nothing at or past the point; capture waits until every owner settled, then exports | Tested; 20′, HT, 60′, 85′ recorded 22 Oct |

```sh
docker compose -p itg-local exec demo-control python /checks/demo_control.py record 20
docker compose -p itg-local exec demo-control python /checks/demo_control.py capture 20
docker compose -p itg-local exec demo-control python /checks/demo_control.py record ht --from 20   # chain HT, 60, 85
```

Point ids: `kickoff`, `20`, `ht`, `60`, `85` (feed `demo_settings`, editable in `/dev/`). Seed routes exist only with `DEMO_SEEDS=1` (default here); without it each owner has no export or restore route. Start and cancel share one rate limit (10/min, burst 5); state and status are limited per client. Contract: [§7a](contracts.md#7a-demo-control-public).

## Machine and troubleshooting

Allow roughly 8–12 GB Docker memory and several GB of free disk for the full stack, more if other projects run. SQL Server and the selected Data API builder image run as `linux/amd64`; Apple Silicon requires working Docker x86 emulation. The other emulators support ARM64. First image downloads can take minutes.

SQL Server stays pinned to 2022 (`2022-latest@sha256:…`), unlike the ETL's own compose and CI (2025): the one `sql` container also stores the Service Bus emulator's state, and Microsoft's emulator documents SQL Server 2022 (or Azure SQL Edge) as its backing store. Upgrade it only after the Service Bus emulator supports a newer version.

- Questions and narratives share the local model. The engine keeps at most `NARRATIVE_MODEL_CONCURRENCY` (default 2) calls in flight so questions get a slot; with three matches the narratives then trail live play by a few minutes. Custom-stat questions chain several calls and took 56–212 s under load, so `QUESTION_TIMEOUT_SECONDS` is 240 and nginx's `/viewer-api/` and `/api/` read timeouts are 250 s. Measured 2026-10-20, three concurrent questions during three matches: engine at 4 calls, 35–90 s with one timeout at the old 90 s limit; at 1, 28–62 s; at 2, custom stats 75–103 s.
- `./dev logs sql` / `./dev logs etl-dab`: diagnose SQL startup or DAB configuration.
- `./dev logs eventhubs` / `./dev logs servicebus`: diagnose emulator configuration.
- The emulators keep no messages across a restart. After a Service Bus restart (it takes minutes under load) the engine, backend and ETL reconnect by themselves. Under heavy host load the Service Bus emulator can stay stuck answering "namespace is being throttled" (code 50002; no narratives arrive, `./dev logs servicebus`): `docker restart itg-local-servicebus-1` clears it. After an Event Hubs restart its sequence numbers start again: the backend and `etl-stream` log the reset, forget their stored positions and read on from now, so runs started afterwards work. Events a consumer had not read before the restart are gone: ETL then holds that match at the last seq before the hole (it never counts a partial history) and the viewer stops there. Run `./dev demo start` again for in-flight matches.
- `./dev up` recreates an emulator or DAB when its mounted config file changed (they read it only at start), and DAB also when an ETL migration changed (it reads the SQL schema only at start).
- `./dev test azure` waits for dependencies, then tests their protocols.
- Second stack beside `itg-local`: every host port is an `ITG_*_PORT` variable (defaults above) and the project name is `ITG_PROJECT_NAME`. `docker compose -p itg-verify-x --env-file local/env.defaults --env-file local/verify.env.example -f local/compose.yaml …` uses its own ports and volumes; [verify.env.example](verify.env.example) lists them.
- Ports busy: put personal changes in ignored `local/compose.override.yaml`; `./dev` loads it automatically. Use Compose's `!override` tag to replace a port list rather than append to it (Compose 2.24.4+). Docker-to-Docker settings remain unchanged.
- `./dev down` preserves SQL/Postgres volumes and the feed's played media; `./dev demo purge` clears match data. Cosmos and messaging state are disposable; rerun tests/seeding after recreation.
- Postgres init SQL runs only on a fresh volume. Later application schema changes need migrations.

Dependency image digests are pinned to the tested builds, including multi-architecture manifests. Upgrade them deliberately and rerun `./dev test azure`. Direct Python tooling dependencies are pinned in `requirements.txt`. Docker must be able to reach public image/package registries on first setup; this is account-free, not an offline installer.

## Licences

Running `ACCEPT_EULA=Y ./dev up backend` or `ACCEPT_EULA=Y ./dev up azure` accepts the [Event Hubs emulator terms](https://github.com/Azure/azure-event-hubs-emulator-installer/blob/main/EMULATOR_EULA.txt), [Service Bus emulator terms](https://github.com/Azure/azure-service-bus-emulator-installer/blob/main/EMULATOR_EULA.txt) and [SQL Server terms](https://go.microsoft.com/fwlink/?LinkId=746388). Each developer should review them; the default is `N`. No login or billing account is needed for these containers.

## Coverage limits

Microsoft emulators exercise application data protocols, not Azure provisioning, production durability, throughput or security. Stream Analytics itself isn't emulated: `etl-stream` applies the ETL's Python reference rules instead; the ETL service owns the real job and its cloud validation. Foundry models are not emulated; the engine and agents use the optional local model. The separate `backend` profile runs the feed, match viewer, question/filter agents, ETL pipeline stand-in and narrative engine. Arbitrary generated-code isolation remains planned.

**LocalStack Azure is optional, not installed:** it [requires an auth token](https://docs.localstack.cloud/azure/getting-started/auth-token/) and [supports Terraform](https://docs.localstack.cloud/azure/connecting/infrastructure-as-code/terraform/). The Microsoft emulators used here have no general Azure Resource Manager endpoint, so Terraform doesn't create their resources; checked-in JSON/SQL does.

Sources checked 2026-10-18: [Event Hubs](https://learn.microsoft.com/en-us/azure/event-hubs/test-locally-with-event-hub-emulator), [Service Bus](https://learn.microsoft.com/en-us/azure/service-bus-messaging/test-locally-with-service-bus-emulator), [Cosmos](https://learn.microsoft.com/en-us/azure/cosmos-db/emulator-linux), [Data API builder](https://learn.microsoft.com/en-us/azure/data-api-builder/deployment/local-container).
