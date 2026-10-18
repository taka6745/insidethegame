# Local integration

Run from the repo root using [`../dev`](../dev). [Quick start](../DEVELOPMENT.md) · [Contracts](contracts.md) · [Verified results](verification.md)

## What runs

| Dependency | Local implementation | Host address |
| --- | --- | --- |
| User databases | PostgreSQL 16, `accounts` + `matchapp` | `localhost:15432` |
| Narrative storage | Microsoft Cosmos vNext emulator | `http://localhost:18081` |
| Cosmos explorer | Emulator UI | `http://localhost:11234` |
| Match events | Microsoft Event Hubs emulator | AMQP `localhost:15672` |
| Notifications | Microsoft Service Bus emulator | AMQP `localhost:15673` |
| Match history | SQL Server 2022 Developer | `localhost:11433` |
| Match GraphQL | Real Data API builder | `http://localhost:15000/graphql` |

Inside Docker use service names and native ports: `postgres:5432`, `cosmos:8081`, `eventhubs:5672`, `servicebus:5672`, `sql:1433`, `graphql:5000`. Example SDK settings are in [settings.py](settings.py); all credentials there are **public local dummy values**, never cloud credentials. Cosmos uses HTTP for local Python development. Host clients must use the mapped ports above.

Only loopback ports are published. Existing projects on ports 3000, 5432 and 4566 are untouched. Avoid exposing this unauthenticated demo stack to a network.

## What tests prove

`./dev test`: three demo profiles, two Postgres databases, Cosmos document write/read/delete. Creates narrative containers if absent.

`./dev test azure`: adds SQL fixture inserts → real GraphQL query, Event Hubs SDK send/receive, Service Bus topic/subscription send/receive. Uses dedicated integration consumers. `IntegrationProbe` messages may also reach application consumers; ignore that type. Checks are repeatable and fail with a nonzero exit status.

`./dev replay`: publishes the three tiny, hand-authored synthetic events **with their original timestamps and IDs**. It does not run at match speed or rebase time. It is useful for consumer development, not a Stream Analytics event-time test. The full replay tool belongs to `data-generation/`.

SQL fixture insertion is explicit test setup, **not an implementation of ETL**. Computed stats, the key-event ledger and narrative GraphQL are still application work.

## Machine and troubleshooting

Allow roughly 8–12 GB Docker memory and several GB of free disk for the full stack, more if other projects run. SQL Server and the selected Data API builder image run as `linux/amd64`; Apple Silicon requires working Docker x86 emulation. The other emulators support ARM64. First image downloads can take minutes.

- `./dev logs sql` / `./dev logs graphql`: diagnose SQL startup or DAB configuration.
- `./dev logs eventhubs` / `./dev logs servicebus`: diagnose emulator configuration.
- `./dev test azure` waits for dependencies, then tests their protocols.
- Ports busy: adjust `ports` in Compose and update host client settings; Docker-to-Docker settings remain unchanged.
- `./dev down` preserves SQL/Postgres volumes. Cosmos and messaging state are disposable; rerun tests/seeding after recreation.
- Postgres init SQL runs only on a fresh volume. Later application schema changes need migrations.

## Licences

Running `ACCEPT_EULA=Y ./dev up azure` accepts the [Event Hubs emulator terms](https://github.com/Azure/azure-event-hubs-emulator-installer/blob/main/EMULATOR_EULA.txt), [Service Bus emulator terms](https://github.com/Azure/azure-service-bus-emulator-installer/blob/main/EMULATOR_EULA.txt) and [SQL Server terms](https://go.microsoft.com/fwlink/?LinkId=746388). Each developer should review them; the default is `N`. No login or billing account is needed for these containers.

## Coverage limits

Microsoft emulators exercise application data protocols, not Azure provisioning, production durability, throughput or security. Stream Analytics isn't supplied here; Luke owns its implementation and cloud validation. Foundry models are not emulated. No agents, generated-code sandbox or frontend are running yet.

**LocalStack Azure is optional, not installed:** it [requires an auth token](https://docs.localstack.cloud/azure/getting-started/auth-token/) and [supports Terraform](https://docs.localstack.cloud/azure/connecting/infrastructure-as-code/terraform/). The Microsoft emulators used here have no general Azure Resource Manager endpoint, so Terraform doesn't create their resources; checked-in JSON/SQL does.

Sources checked 2026-10-18: [Event Hubs](https://learn.microsoft.com/en-us/azure/event-hubs/test-locally-with-event-hub-emulator), [Service Bus](https://learn.microsoft.com/en-us/azure/service-bus-messaging/test-locally-with-service-bus-emulator), [Cosmos](https://learn.microsoft.com/en-us/azure/cosmos-db/emulator-linux), [Data API builder](https://learn.microsoft.com/en-us/azure/data-api-builder/deployment/local-container).
