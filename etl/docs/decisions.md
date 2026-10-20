# Decisions

> **In short:** the built ETL follows the [original design](design/original-design.md) service for service; it adds an event format, a match table, period notifications and the tooling to prove the cloud output correct, and it is tuned for 10x replays.

| | |
| --- | --- |
| **Design** | [design/original-design.md](design/original-design.md), the design board |

## 1. Kept from the design

*In short: the same five Azure services in the same roles.*

- Event Hubs → Stream Analytics → serverless Azure SQL (`rawEvents`, `keyEvents`, `minuteStats`, view `matchStatsAsOf`) → Data API builder on Container Apps.
- Service Bus notifications `KeyEventDetected` and `MinuteClosed`.
- Event-time windows aligned with kickoff, tolerance for late arrivals, VAR corrections as negative goal deltas.
- The user backend reads live events from Event Hubs through its own consumer group.

## 2. Added or changed

*In short: each addition answers a question the design left open.*

| Design | Built | Why |
| --- | --- | --- |
| Event format open | Opta MA1/MA3 style, schema and codes in `contracts/` | A widely known format with qualifiers for every key event |
| — | `matches` table from MA1 | Consumers need team names and home/away |
| Two notification types | Plus `PeriodStarted` / `PeriodEnded` | The narrative engine needs half and full time |
| Replay from data generation | Temporary `seeder/` in the ETL | Data generation does not exist yet |
| — | Python `reference/` and `devtools verify` | Stream Analytics has no local emulator; the reference proves the cloud output |
| Late arrivals "allowed" | 2 s out of order, 5 s late, 6 s windows | Sized for 10x replays |
| Managed identity | Managed identity to SQL; scoped keys for Event Hubs and Service Bus | Contributor cannot create role assignments |
| — | DAB anonymous read | Synthetic dev data; to be restricted |

## 3. Open items

*In short: what remains before the demo.*

| Item | Notes |
| --- | --- |
| Reconcile with the demo stand-in's contract | The local stack and user backend use [`demo_etl/`](components/demo-etl.md)'s `MatchSnapshotReady` and `questionData` GraphQL; the Azure pipeline publishes per-minute notifications and serves the DAB schema, with stats in Azure SQL (root `AGENTS.md` plans Cosmos DB). Agree one contract with the user backend and narrative engine, then swap the stand-in out |
| Real-time (1x) run | `window_seconds = 60`, probably larger late tolerance; waits for the other services |
| Late, duplicate and out-of-order injection | The seeder cannot inject them yet |
| Subscription backlog | Consider a TTL on `narrative-engine`, or purging before a match |
| Hand the replay to data generation | Move or replace `seeder/` when data generation exists |
| Deploy the comment change in `query.asaql` | The `etltools` → `reference` rename changed a comment; the next apply updates the job (stop it first) |

## 4. LATER (needs Owner or RBAC Administrator)

*In short: search `LATER` in `infra/` and `seeder/replay.py`.*

- Managed identity for Stream Analytics' Event Hubs input and Service Bus output, the seeder and consumers; then remove the shared access keys.
- Restrict DAB to the services instead of anonymous read.
