# Development

> **In short:** Docker is the only tool; allow 8–12 GB of Docker memory; most problems are an emulator that needs a restart.

| | |
| --- | --- |
| **Needs** | Docker Desktop or Engine + Compose; macOS, Linux or WSL |
| **Memory** | 8–12 GB for the full stack; SQL Server and DAB run as `linux/amd64` (Apple Silicon needs x86 emulation) |
| **Tests** | `./dev test [azure\|backend]`, `python3 -m pytest -q local/test_demo_control.py` |

## 1. Machine

*In short: big images, one-time downloads.*

First image downloads take minutes; Docker must reach public registries on first setup (account-free, not offline). SQL Server stays on 2022 (unlike the ETL's own compose and CI, 2025): the one `sql` container also stores the Service Bus emulator's state, which Microsoft documents on SQL Server 2022.

A second stack beside `itg-local`: `docker compose -p itg-verify-x --env-file local/env.defaults --env-file local/verify.env.example -f local/compose.yaml …` uses its own ports and volumes.

## 2. Troubleshooting

*In short: logs first, then restart the one container.*

- Questions and narratives share the local model. The engine keeps at most `NARRATIVE_MODEL_CONCURRENCY` (default 2) calls in flight so questions get a slot; with three matches narratives trail live play by a few minutes. Custom-stat questions took 56–212 s under load, so `QUESTION_TIMEOUT_SECONDS` is 240 and nginx's `/viewer-api/` and `/api/` read timeouts are 250 s.
- `./dev logs sql` / `./dev logs etl-dab`: SQL startup or DAB configuration. `./dev logs eventhubs` / `./dev logs servicebus`: emulator configuration.
- The emulators keep no messages across a restart. After a Service Bus restart the engine, backend and ETL reconnect by themselves. A Service Bus emulator stuck on "namespace is being throttled" (code 50002) under heavy host load: `docker restart itg-local-servicebus-1`.
- After an Event Hubs restart its sequence numbers start again: the backend and `etl-stream` forget their stored positions and read on from now. Events not read before the restart are gone, so ETL holds that match at the last seq before the hole and the viewer stops there; run `./dev demo start` again.
- After a hard host restart the Cosmos emulator can keep a stale `postmaster.pid` and never become ready: remove it inside the container and restart that container.
- `./dev down` keeps SQL/Postgres volumes and the feed's played media; `./dev demo purge` clears match data. Cosmos and messaging state are disposable. Postgres init SQL runs only on a fresh volume.

## 3. Licences

*In short: each developer accepts Microsoft's terms; the default is `N`.*

`ACCEPT_EULA=Y ./dev up backend` or `ACCEPT_EULA=Y ./dev up azure` accepts the [Event Hubs emulator terms](https://github.com/Azure/azure-event-hubs-emulator-installer/blob/main/EMULATOR_EULA.txt), [Service Bus emulator terms](https://github.com/Azure/azure-service-bus-emulator-installer/blob/main/EMULATOR_EULA.txt) and [SQL Server terms](https://go.microsoft.com/fwlink/?LinkId=746388). No login or billing account is needed.

## 4. Coverage limits

*In short: protocols, not Azure.*

The emulators exercise application data protocols, not Azure provisioning, durability, throughput or security. Stream Analytics isn't emulated: `etl-stream` applies the ETL's Python reference rules; the ETL owns the real job and its cloud validation. Foundry models aren't emulated; the engine and agents use the local model. Arbitrary generated-code isolation remains planned.

LocalStack Azure is optional and not installed: it [requires an auth token](https://docs.localstack.cloud/azure/getting-started/auth-token/). The Microsoft emulators have no Azure Resource Manager endpoint, so checked-in JSON/SQL, not Terraform, creates their resources. Sources checked 2026-10-18: [Event Hubs](https://learn.microsoft.com/en-us/azure/event-hubs/test-locally-with-event-hub-emulator), [Service Bus](https://learn.microsoft.com/en-us/azure/service-bus-messaging/test-locally-with-service-bus-emulator), [Cosmos](https://learn.microsoft.com/en-us/azure/cosmos-db/emulator-linux), [Data API builder](https://learn.microsoft.com/en-us/azure/data-api-builder/deployment/local-container).
