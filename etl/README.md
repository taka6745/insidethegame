# Match data / ETL

> **In short:** turns a stream of Opta-style match events into queryable history, a key-event ledger and running match statistics (Azure SQL behind GraphQL), and announces closed minutes and key events on Service Bus. Implemented and tested ([status](docs/overview.md#3-status-by-area)).

[Documentation](docs/README.md) · [Shared local setup](../DEVELOPMENT.md)

![ETL owns standard statistics and historical events](architecture.svg)

Azure: Event Hubs → Stream Analytics → Azure SQL serverless → Data API builder, plus Service Bus. Locally, `local_stream/` stands in for Stream Analytics in `./dev up backend` (GraphQL `http://localhost:15001/graphql`); on Azure the same image serves only the purge and demo-seed API and the SPADL post-processor ([local-stream](docs/components/local-stream.md)).

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

Setup and tests: [development §1](docs/development.md#1-setup); folders: [docs index](docs/README.md).
