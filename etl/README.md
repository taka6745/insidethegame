# Match data / ETL

[Documentation](docs/README.md) · [Demo API](docs/demo-api.md) · [Shared local setup](../DEVELOPMENT.md)

![ETL owns standard statistics and historical events](architecture.svg)

**Implemented, tested and deployed to dev.** Turns a stream of Opta-style match events into queryable history, a key-event ledger and running match statistics (Azure SQL behind a GraphQL API), and announces closed minutes and key events on Service Bus. Event Hubs → Stream Analytics → Azure SQL serverless → Data API builder, plus Service Bus.

The shared local Docker stack runs a **recorded-match stand-in** instead (`demo_etl/`: the GRF recording, PostgreSQL, Python GraphQL, `MatchSnapshotReady` notifications), described in [docs/components/demo-etl.md](docs/components/demo-etl.md).

| | |
| --- | --- |
| **Documentation** | [docs/](docs/README.md): overview, architecture, one page per component, development, deployment, decisions |
| **For consumers** | [contracts/](contracts/README.md): GraphQL queries, Service Bus messages, key-event conventions (Azure pipeline); [demo-api.md](docs/demo-api.md) (stand-in) |

`demo_etl/` is a replaceable demo implementation, separate from the future Stream Analytics job. It preserves corrections, tombstones and snapshot watermarks. Possession comes from measured simulator ownership; unsupported metrics are unavailable. Opta-style v3 events (location, possession IDs, qualifiers, stoppage-time clock) are accepted and served through GraphQL — unit-tested and run with the 90-minute recording in the integrated Docker stack (20 October 2026). Synthetic football is not an official Opta feed or a real fixture.

```sh
cd etl && python -m venv .venv && .venv/Scripts/pip install -r requirements-test.txt   # Windows path shown
.venv/Scripts/python -m pytest tests
.venv/Scripts/python -m devtools local-up        # SQL Server + DAB in Docker, GraphQL on :5000
```

| Folder | Contents |
| --- | --- |
| `contracts/` | Event schema, Opta codes, what consumers can rely on |
| `seeder/` | Synthetic match and replay to Event Hubs (temporary, until data generation exists) |
| `stream-analytics/` | The Stream Analytics query and JavaScript UDFs |
| `sql/` | Database migrations: tables and the `matchStatsAsOf` view |
| `dab/` | Data API builder configuration (the GraphQL API) |
| `reference/` | The same rules in Python: the expected result for tests and verification |
| `devtools/` | Developer commands: local stack, loading, verification, job start/stop |
| `infra/` | Terraform for Azure dev |
| `tests/` | Pytest suite (pipeline and stand-in) |
| `docs/` | Documentation; original design material in `docs/design/` |
| `demo_etl/` | The [recorded-match stand-in](docs/components/demo-etl.md) for the local Docker stack (`Dockerfile`) |
