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
| — | DAB anonymous read | Internal ingress only: reachable from the backend and engine in the same environment |
| — | Watermark marks from a second, arrival-ordered read of the hub; Azure SQL `INSTEAD OF INSERT` triggers turn them into `matchProgress` | Stream Analytics writes each output separately and append-only, so only SQL can tell when everything a watermark promises is committed |
| Stats on canonical events | SPADL actions converted from MA3 in ETL (`spadlActions`); stats, rules and context on SPADL | One standard action vocabulary for prompts, filters and formulas; MA3 is the provider-realistic stream |
| — | Trend indicators as read-time SQL procedures (`trendsAtSeq`, `trendSpellsAtSeq`, `trendMinutesAtSeq`) with a Python twin; thresholds and `enabled` in the `trendDefinitions` table, seeded from the S1 v2 experiment (`014`: momentum, fast breaks, contests, aggression and long-ball share disabled; pressure spells only alongside territory) | Exact at any snapshot, so a backlog equals live, and purge needs nothing new; no Stream Analytics change on Azure. Disabled trends stay computable for re-enabling with real data ([trends](components/trends.md)) |
| — | Demo seeds as an admin-API adapter (`local_stream/demo_seeds.py`, `DEMO_SEEDS=1` only): export a match's rows, restore them under a new matchId, then the worker reloads from SQL as after a restart | Mid-match demo starts with real history; core code never branches on a demo; absent in a production release |
| Job always on while deployed | Stream Analytics started by Event Hubs traffic and stopped after 30 quiet minutes (`stream_schedule.tf`, guard runbook) | It bills while running; judging leaves the build up for weeks |
| — | Tombstones on Azure: triggers drop rows of purged matches; the purge is the `etl-stream` image as a Container App (`ETL_ROLE=admin`, bearer token) | Stream Analytics cannot read SQL state per event (SQL reference data needs SQL logins; the server is Entra-only) |

## 3. Open items

*In short: what remains before the demo.*

| Item | Notes |
| --- | --- |
| Use SPADL for football action data | **Implemented locally (2026-10-21):** contract and ETL implemented and tested: MA3 → standard SPADL by a pure-Python port of socceraction 1.5.3 (exact parity on all three recordings), live finalisation (`finalSeq`, `spadlSeq`), `spadlActions` via DAB, the [post-processor](components/spadl.md) (`etl-stream` thread; `ETL_ROLE=spadl` app, applied 22 Oct) and the stat catalogue redefined on SPADL ([mapping](../../local/contracts.md#4-stat-catalogue)). Backend rules, questions and replays and the engine's context read it; run on the shared stack with three concurrent matches ([verification](../../local/verification.md)). The Azure run remains |
| Deploy multi-match read models to Azure | **Implemented and tested locally; applied 22 Oct (match run on Azure pending):** Stream Analytics outputs for POS, teams, players, canonical events and watermark marks, the `match-progress` input, Azure SQL triggers (tombstones, watermark, status), the purge API app and registry ([deployment](deployment.md#2-deploying)), all applied by `./dev azure up` on 22 Oct |
| Real-time (1x) run | `./dev azure up` sets `window_seconds = 60` (the feed plays in real time); late tolerance may need raising; part of the pending Azure acceptance |
| Seeds on Azure | Seeds must be recorded on Azure against its schema (a fingerprint mismatch is refused, `409`) |
| Late, duplicate and out-of-order injection | The seeder cannot inject them yet |
| Subscription backlog | Consider a TTL on `narrative-engine`, or purging before a match |
| Hand the replay to data generation | The feed (`data-generation/feed/`) now produces every match; `seeder/` stays a developer tool for synthetic replays and `devtools verify` |
| Deploy the comment change in `query.asaql` | The `etltools` → `reference` rename changed a comment; the next apply updates the job (stop it first) |

## 4. LATER (needs Owner or RBAC Administrator)

*In short: search `LATER` in `infra/` and `seeder/replay.py`.*

- Managed identity for Stream Analytics' Event Hubs input and Service Bus output, the seeder and consumers; then remove the shared access keys.
