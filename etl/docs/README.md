# ETL documentation

> **In short:** the ETL turns a live stream of Opta-style match events into queryable history, a key-event ledger and running statistics (Azure SQL behind a GraphQL API), and announces closed minutes and key events on Service Bus. Start with the overview, then the architecture; each component page maps to one folder.

Every page follows the same layout: an **In short** summary and a facts table at the top, then numbered sections that each open with a one-line *In short*.

## Contents

```
docs/
├── README.md                 this index
├── overview.md               what the ETL does, status, inputs and outputs, glossary
├── architecture.md           diagram, components, runtime flow, data model, Azure resources
├── components/               one page per folder in etl/
│   ├── seeder.md             synthetic match generator and replay to Event Hubs
│   ├── stream-analytics.md   the Stream Analytics query and JavaScript UDFs
│   ├── sql.md                tables and the matchStatsAsOf view
│   ├── dab.md                Data API builder: the GraphQL API
│   ├── reference.md          Python reference implementation of the rules (and the SPADL converter)
│   ├── spadl.md              SPADL post-processor: MA3 → spadlActions
│   ├── trends.md             trend indicators at a snapshot (SQL procedures + reference)
│   ├── devtools.md           local stack, loading, verification, job start/stop
│   └── local-stream.md       local Stream Analytics stand-in, purge API and demo seeds
├── development.md            local setup, stand-ins for Azure, commands, tests
├── deployment.md             Terraform, setup, running a replay, costs
├── decisions.md              design versus implementation, open items, LATER list
└── design/                   original design material, kept for history (not updated)
    ├── original-design.md    the ETL section of the design stage README
    └── design-board.svg      export of the board's ETL section
```

## Where to start

| If you want to… | Read |
| --- | --- |
| Understand the ETL in five minutes | [overview.md](overview.md) |
| See how an event becomes a row and a notification | [architecture.md](architecture.md) |
| Query the data or consume notifications | [../contracts/README.md](../contracts/README.md) |
| Run it on your machine | [development.md](development.md) |
| Run the whole product locally | [../../DEVELOPMENT.md](../../DEVELOPMENT.md), [local-stream](components/local-stream.md) |
| Deploy it or run a live replay | [deployment.md](deployment.md) |
| Know what differs from the original design and why | [decisions.md](decisions.md) |

## Code layout at a glance

| Folder | Contents | Page |
| --- | --- | --- |
| `contracts/` | Event schema, Opta codes, consumer contracts | [contracts](../contracts/README.md) |
| `seeder/` | Synthetic match and replay (temporary, until data generation exists) | [seeder](components/seeder.md) |
| `stream-analytics/` | Job query and UDFs | [stream-analytics](components/stream-analytics.md) |
| `sql/` | Database migrations | [sql](components/sql.md), [trends](components/trends.md) |
| `dab/` | Data API builder configuration | [dab](components/dab.md) |
| `reference/` | Python version of the rules, the expected result for tests; the SPADL converter | [reference](components/reference.md) |
| `spadl/` | SPADL post-processor (a task in `etl-stream`; `ETL_ROLE=spadl` on Azure) | [spadl](components/spadl.md) |
| `devtools/` | Developer commands (not deployed) | [devtools](components/devtools.md) |
| `infra/` | Terraform for Azure dev | [deployment](deployment.md) |
| `tests/` | Pytest suite (pipeline, catalogue, local stream, SQL) | [development](development.md#4-tests) |
| `docker-compose.yml` | Local SQL Server and Data API builder | [development](development.md#2-local-stand-ins) |
| `local_stream/` | Local Stream Analytics stand-in for the shared Docker stack (`Dockerfile`) | [local-stream](components/local-stream.md) |
