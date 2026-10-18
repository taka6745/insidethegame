# Verified locally — 2026-10-18

Machine: Apple Silicon macOS, Docker Engine 29.7.2, Compose 5.5.1. Existing unrelated containers were left running.

| Check | Result |
| --- | --- |
| `./dev up` + `./dev test` | Passed: Postgres profiles/two databases and Cosmos document round trip. |
| `ACCEPT_EULA=Y ./dev up azure` | Started: Event Hubs, Service Bus, SQL Server, Azurite and Data API builder. Licence acceptance explicitly authorised by the local user. |
| `./dev test azure` | Passed: SDK event send/receive, both Service Bus topic deliveries, SQL fixture seed and GraphQL history query. |
| `./dev replay` | Published the three synthetic fixture events successfully. |
| `./dev terraform check` | Passed: formatting, Azure provider schema validation and one mocked plan test with four boundary assertions. No Azure account or deployment. |
| Guide checks | Local Markdown links checked; SVG rendered and visually inspected. |
| Onboarding follow-up | `./dev doctor`, automatic checks on `up azure`, and invalid-mode/licence guards passed. Pinned image manifests checked for ARM64/AMD64 support where applicable. |
| Terraform follow-up | Passed without deprecated Event Hub fields, using the host user's UID/GID in Docker. |
| Fresh GitHub clone | Full `up azure` checks passed in a separate Compose project with empty volumes. No ignored workspace files or cached Terraform provider directory copied over. Docker image/build caches were reused. |
| Host connection examples | Both PostgreSQL databases, SQL, Cosmos, GraphQL, Event Hubs and Service Bus passed through the published host ports, using a Docker test client via `host.docker.internal`. GraphQL also queried directly from macOS. |
| Stop/start recovery | Fresh-clone stack passed `down` → `up azure` with SQL/Postgres volumes retained. Fixture seeding remained repeatable; all messaging/database checks passed again. Temporary test containers/volumes were then removed. |

These checks exercise actual local containers. They do **not** validate the Stream Analytics job, real Foundry models, application services, frontend, generated-code isolation or a cloud deployment. Terraform's mock-provider checks are also separate from runtime integration.

Re-run the commands on a new machine. Emulator behaviour differs from Azure; in particular messages/state, identity, throughput and resource-management APIs are not cloud-equivalent.

## User-backend harness — 2026-10-18

`./dev up backend` built and started the API, fake ETL and fake narrative services against the existing local Postgres. **39 tests passed**, including all 12 buckets, real database persistence/concurrent pins, session takeover, repeated socket disconnects, stat replacement, event corrections and the coding-agent repair contract.

The separate live smoke test replayed the JSONL through both fake services, read their GraphQL APIs and checked the backend WebSocket. It verified header count **4**, Chelsea goals **1**, United goals **0** after VAR, only the matching bucket narrative, duplicate-event protection and retained pins after session takeover. Tests use synthetic data; no model or Azure account was used.

One non-failing dependency warning: Starlette deprecates its HTTPX-based test client in favour of HTTPX2. The current pinned direct dependencies passed. Real agents, generated-code execution, production broker consumers and Azure deployment remain unverified/unimplemented; see [coverage limits](../user-backend/docs/testing.md).

## ETL stat ownership — 2026-10-18

`./dev up backend`: **42 tests passed**, followed by the live Docker replay check. New tests enforce unchanged ETL-provided standard values, no raw-history fetch for standard cards, and a separate event-history query for custom pins/investigation. Standard values are no longer redundantly calculated in the runtime backend adapter. Cosmos stat storage and SQL history remain the planned production ETL stores; these tests use the fake ETL GraphQL service.
