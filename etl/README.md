# Match data / ETL

![Match events become queryable history, stats and notifications](architecture.svg)

**Implemented, tested and deployed to dev.** Turns a stream of Opta-style match events into queryable history, a key-event ledger and running match statistics (Azure SQL behind a GraphQL API), and announces closed minutes and key events on Service Bus. Event Hubs → Stream Analytics → Azure SQL serverless → Data API builder, plus Service Bus.

| | |
| --- | --- |
| **Documentation** | [docs/](docs/README.md): overview, architecture, one page per component, development, deployment, decisions |
| **For consumers** | [contracts/](contracts/README.md): GraphQL queries, Service Bus messages, key-event conventions |

```sh
cd etl && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows path shown
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
| `tests/` | Pytest suite |
| `docs/` | Documentation; original design material in `docs/design/` |
