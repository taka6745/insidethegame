# Match data / ETL

[Documentation](docs/README.md) · [Shared local setup](../DEVELOPMENT.md)

![ETL owns standard statistics and historical events](architecture.svg)

**Implemented and tested; applied to Azure 22 Oct for the Azure test (demo acceptance pending)** (the multi-match outputs, Azure SQL triggers and purge API are tested locally; their Azure match run is part of the acceptance: [decisions](docs/decisions.md#3-open-items)). Turns a stream of Opta-style match events into queryable history, a key-event ledger and running match statistics (Azure SQL behind a GraphQL API), and announces closed minutes and key events on Service Bus. Event Hubs → Stream Analytics → Azure SQL serverless → Data API builder, plus Service Bus.

**Local pipeline stand-in (`local_stream/`): implemented and tested locally; not deployed as a worker (on Azure the same image serves only the purge and demo-seed API).** `./dev up backend` also runs this pipeline's SQL schema and Data API builder 2.1.5 config on the stack's SQL Server (database `insidethegame`, GraphQL `http://localhost:15001/graphql`, `http://etl-dab:5000/graphql` inside Docker). A Python worker replaces Stream Analytics: it reads MA1, MA3, POS and `MatchEvent` v2 from Event Hubs (consumer group `stream-analytics`), applies `reference/` one message at a time, writes `matches`/`rawEvents`/`keyEvents`/`minuteStats` plus the multi-match read models (teams, players, canonical events, possession samples, watermarks; [contracts](../local/contracts.md#3-etl-graphql-dab)), serves the 126-stat SPADL catalogue (42 kinds × 3 scopes) through `executeStatsAtSeq`, purges per match (`POST /admin/matches/purge`), and sends the [notifications](contracts/README.md#output-2-service-bus-topic-match-notifications) to `match-notifications` (subscription `narrative-live`, filtered on `notificationType`). Each feed run is its own match: `{fixture}-{first 8 hex of run id}`. The earlier recorded-match stand-in (`demo_etl/`) is deleted; its stat catalogue lives here (`statDefinitions`, `executeStatsAtSeq`).

```text
feed ─ MA1/MA3/POS/MatchEvent v2 ─→ Event Hubs ─→ local_stream ─→ SQL Server ─→ etl-dab GraphQL
                                              └─ outbox ─→ Service Bus match-notifications → narrative-live
```

Windows are 60-second event-time tumbling windows; a minute closes when the next minute's first event arrives, or after 75 s without messages (paused feed or full time). Rows, closed windows, the Event Hubs checkpoint and outgoing notifications commit in one transaction, so a restart neither loses nor double-counts (unit-tested, and checked against `devtools verify` after a hard kill mid-match). Limits: one worker process; an event that arrives after its window closed joins the next window, like Stream Analytics' adjust policy.

| | |
| --- | --- |
| **Documentation** | [docs/](docs/README.md): overview, architecture, one page per component, development, deployment, decisions |
| **For consumers** | [contracts/](contracts/README.md): GraphQL queries, Service Bus messages, key-event conventions (Azure pipeline) |
| **Demo seeds** | `local_stream/demo_seeds.py`: export and restore one match's rows on the admin API, mounted only with `DEMO_SEEDS=1` (local compose, judge build); [local-stream §4](docs/components/local-stream.md#4-demo-seeds-demo_seeds-only) |
| **Spend guard** | Stream Analytics runs only while match events flow (`infra/stream_schedule.tf`, [stream-analytics §6](docs/components/stream-analytics.md#6-run-only-while-matches-play)) |

The catalogue counts final SPADL actions converted from MA3 (`finalSeq ≤ seq`); cards come from MA3 card rows and possession from the feed's POS samples; metrics the MA1 capabilities don't cover are unavailable. Synthetic football is not an official Opta feed.

```sh
cd etl && python -m venv .venv && .venv/Scripts/pip install -r requirements-test.txt   # Windows path shown
.venv/Scripts/python -m pytest tests
.venv/Scripts/python -m devtools local-up        # SQL Server + DAB in Docker, GraphQL on :5000
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
