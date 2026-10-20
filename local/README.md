# Local integration

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
| Service Bus storage / SQL check (`backend` + `azure`) | SQL Server 2022 Developer | `localhost:11433` |
| SQL GraphQL check (`azure` profile) | Real Data API builder | `http://localhost:15000/graphql` |
| User backend (`backend` profile) | FastAPI + WebSocket harness | `http://localhost:18000/docs` |
| Demo ETL (`backend` profile) | Recorded GRF events + calculated stats | `http://localhost:18010/graphql` |
| ETL databases (`backend` profile) | PostgreSQL `etl_history` + `etl_stats` | `localhost:15432` |
| Narrative stub (`backend` profile) | 144 authored narratives + neutral recap archive; own SQLite volume | `http://localhost:18011/graphql` |
| Match viewer (`backend` profile) | nginx + optional aligned video | `http://localhost:18020/` |

Inside Docker use service names and native ports: `postgres:5432`, `etl:8000`, `narrative:8000`, `backend:8000`, `cosmos:8081`, `eventhubs:5672`, `servicebus:5672`, `sql:1433`, `graphql:5000`. Example SDK settings are in [settings.py](settings.py); all credentials there are **public local dummy values**, never cloud credentials. Cosmos uses HTTP for local Python development. Host clients must use the mapped ports above.

Running your application directly on your laptop? Copy the relevant values from [connections.env.example](connections.env.example) into that service's ignored `.env`. The file is not automatically loaded; your application's config loader owns that. GraphQL example:

```sh
curl http://localhost:15000/graphql \
  -H 'Content-Type: application/json' \
  --data '{"query":"{ rawEvents(first: 3) { items { id type } } }"}'
```

Only loopback ports are published. Existing projects on ports 3000, 5432 and 4566 are untouched. Avoid exposing this unauthenticated demo stack to a network.

## What tests prove

`ACCEPT_EULA=Y ./dev up backend` builds the viewer, backend, ETL and narrative stub, starts both messaging emulators, then runs backend tests and a broker integration check. `./dev test backend` repeats the checks without resetting the active replay. Review the [licences](#licences) first; no account is needed.

```text
Replay → Event Hubs ─┬→ shared backend event consumer
                    └→ ETL → Service Bus match-notifications
                                      ↓
                              narrative stub
                                      ↓
                          Service Bus narratives → backend → viewer
```

ETL owns PostgreSQL history/stat projections; the narrative stub owns SQLite and 144 manually authored versions. GraphQL provides historical events, computed stats and recap history. These remain replaceable demo repositories. Azure SQL/Cosmos adapters, Stream Analytics and generated narratives are still planned.

The broker check publishes a unique run through the actual SDKs, verifies first-event redelivery and selected match watermarks, reads both GraphQL services and observes the `narratives` integration subscription. It restores the current live watermark afterwards. Isolated backend tests use empty broker settings and their existing HTTP doubles. No cloud throughput or distributed ownership is proved by these checks.

Run broker probes serially while replay is idle or finished. They share the demo narrative cursor: a running match correctly suppresses older probe snapshots from live publication. Both probes refuse an active replay and detect it starting during their wait; they never stop or reset the viewer.

`./dev reset backend` creates a fresh match run (account profiles remain; match-scoped state resets). `./dev replay backend` starts the [12-minute GRF recording](../data-generation/docs/grf-demo.md). `./dev` mounts `.local/grf-demo-chelsea-united-v3/match.mp4` automatically when present, or accepts `DEMO_VIDEO_PATH`. Media stays ignored; the event/stat/narrative demo works without it.

`./dev test`: three demo profiles, two Postgres databases, Cosmos document write/read/delete. Creates narrative containers if absent.

`./dev test azure`: adds SQL fixture inserts → real GraphQL query, Event Hubs SDK send/receive, Service Bus topic/subscription send/receive. Uses dedicated integration consumers. `IntegrationProbe` messages may also reach application consumers; ignore that type. Checks are repeatable and fail with a nonzero exit status.

`./dev replay`: publishes the three tiny, hand-authored synthetic events **with their original timestamps and IDs**. It does not run at match speed or rebase time. It is useful for consumer development, not a Stream Analytics event-time test. The full replay tool belongs to `data-generation/`.

The Azure-profile SQL fixture insertion is an infrastructure check, **not the demo ETL**. The separate backend profile implements recorded-match history, standard stats and narrative GraphQL. Azure SQL/Cosmos writers, Stream Analytics and Azure deployment remain planned.

## Machine and troubleshooting

Allow roughly 8–12 GB Docker memory and several GB of free disk for the full stack, more if other projects run. SQL Server and the selected Data API builder image run as `linux/amd64`; Apple Silicon requires working Docker x86 emulation. The other emulators support ARM64. First image downloads can take minutes.

- `./dev logs sql` / `./dev logs graphql`: diagnose SQL startup or DAB configuration.
- `./dev logs eventhubs` / `./dev logs servicebus`: diagnose emulator configuration.
- `./dev test azure` waits for dependencies, then tests their protocols.
- Ports busy: put personal changes in ignored `local/compose.override.yaml`; `./dev` loads it automatically. Use Compose's `!override` tag to replace a port list rather than append to it (Compose 2.24.4+). Docker-to-Docker settings remain unchanged.
- `./dev down` preserves SQL/Postgres and narrative SQLite volumes. Cosmos and messaging state are disposable; rerun tests/seeding after recreation.
- Postgres init SQL runs only on a fresh volume. Later application schema changes need migrations.

Dependency image digests are pinned to the tested builds, including multi-architecture manifests. Upgrade them deliberately and rerun `./dev test azure`. Direct Python tooling dependencies are pinned in `requirements.txt`. Docker must be able to reach public image/package registries on first setup; this is account-free, not an offline installer.

## Licences

Running `ACCEPT_EULA=Y ./dev up backend` or `ACCEPT_EULA=Y ./dev up azure` accepts the [Event Hubs emulator terms](https://github.com/Azure/azure-event-hubs-emulator-installer/blob/main/EMULATOR_EULA.txt), [Service Bus emulator terms](https://github.com/Azure/azure-service-bus-emulator-installer/blob/main/EMULATOR_EULA.txt) and [SQL Server terms](https://go.microsoft.com/fwlink/?LinkId=746388). Each developer should review them; the default is `N`. No login or billing account is needed for these containers.

## Coverage limits

Microsoft emulators exercise application data protocols, not Azure provisioning, production durability, throughput or security. Stream Analytics isn't supplied here; the ETL service owns its implementation and cloud validation. Foundry models are not emulated. The separate `backend` profile runs the match viewer, question/filter agents, recorded-match ETL and authored narrative stub. Arbitrary generated-code isolation remains planned.

**LocalStack Azure is optional, not installed:** it [requires an auth token](https://docs.localstack.cloud/azure/getting-started/auth-token/) and [supports Terraform](https://docs.localstack.cloud/azure/connecting/infrastructure-as-code/terraform/). The Microsoft emulators used here have no general Azure Resource Manager endpoint, so Terraform doesn't create their resources; checked-in JSON/SQL does.

Sources checked 2026-10-18: [Event Hubs](https://learn.microsoft.com/en-us/azure/event-hubs/test-locally-with-event-hub-emulator), [Service Bus](https://learn.microsoft.com/en-us/azure/service-bus-messaging/test-locally-with-service-bus-emulator), [Cosmos](https://learn.microsoft.com/en-us/azure/cosmos-db/emulator-linux), [Data API builder](https://learn.microsoft.com/en-us/azure/data-api-builder/deployment/local-container).
