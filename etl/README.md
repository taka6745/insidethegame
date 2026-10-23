# Match data / ETL

> **In short:** turns a stream of Opta-style match events into queryable history, a key-event ledger and running match statistics (Azure SQL behind GraphQL), and announces closed minutes and key events on Service Bus. Implemented, tested and deployed ([status](docs/overview.md#3-status-by-area)).

[Documentation](docs/README.md) · [Shared local setup](../DEVELOPMENT.md)

![ETL owns standard statistics and historical events](architecture.svg)

Azure: Event Hubs → Stream Analytics → Azure SQL serverless → Data API builder, plus Service Bus. Locally, `local_stream/` stands in for Stream Analytics in `./dev up backend` (GraphQL `http://localhost:15001/graphql`); on Azure the same image serves only the purge and demo-seed API ([local-stream](docs/components/local-stream.md)).

```text
feed ─ MA1/MA3/POS/MatchEvent v2 ─→ Event Hubs ─→ local_stream ─→ SQL Server ─→ etl-dab GraphQL
                                              └─ outbox ─→ Service Bus match-notifications → narrative-live
```

| | |
| --- | --- |
| **Documentation** | [docs/](docs/README.md): overview, architecture, one page per component, development, deployment, decisions |
| **For consumers** | [contracts/](contracts/README.md): GraphQL queries, Service Bus messages, key-event conventions (Azure pipeline) |
| **Demo seeds** | `local_stream/demo_seeds.py`: export and restore one match's rows on the admin API, mounted only with `DEMO_SEEDS=1` (local compose, demo build); [local-stream §4](docs/components/local-stream.md#4-demo-seeds-demo_seeds-only) |
| **Spend guard** | Stream Analytics runs only while match events flow (`infra/stream_schedule.tf`, [stream-analytics §6](docs/components/stream-analytics.md#6-run-only-while-matches-play)) |

The catalogue counts final SPADL actions converted from MA3 (`finalSeq ≤ seq`); cards come from MA3 card rows and possession from the feed's POS samples; metrics the MA1 capabilities don't cover are unavailable. Synthetic football is not an official Opta feed.

```sh
cd etl && python3 -m venv .venv && .venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests
.venv/bin/python -m devtools local-up        # SQL Server + DAB in Docker, GraphQL on :5000
```

| Folder | Contents |
| --- | --- |
| `contracts/` | Event schema, Opta codes, what consumers can rely on |
| `seeder/` | Synthetic test match and replay to Event Hubs (developer tooling; the feed is the stack's producer) |
| `stream-analytics/` | The Stream Analytics query and JavaScript UDFs |
| `sql/` | Database migrations: tables, the `matchStatsAsOf` view, multi-match read models, the stat catalogue |
| `dab/` | Data API builder configuration (the GraphQL API) |
| `reference/` | The same rules in Python: the expected result for tests and verification |
| `devtools/` | Developer commands: local stack, loading, verification, job start/stop |
| `spadl/` | SPADL post-processor: MA3 rows → final `spadlActions` (thread in `etl-stream`; `ETL_ROLE=spadl` on Azure) |
| `local_stream/` | Local Stream Analytics stand-in for the shared Docker stack (worker, SQL init, state tables) |
| `infra/` | Terraform for Azure dev |
| `tests/` | Pytest suite (pipeline, catalogue, local stream, SQL) |
| `docs/` | Documentation; original design material in `docs/design/` |
