# Decisions

> **In short:** the built ETL follows the [original design](design/original-design.md) service for service; it adds an event format, a match table, period notifications and the tooling to prove the cloud output correct; it runs real time on Azure (Terraform defaults suit 10x replays).

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
| Replay from data generation | `seeder/` kept as a developer tool; the feed (`data-generation/feed/`) produces every match | Synthetic replays and `devtools verify` need no feed |
| — | Python `reference/` and `devtools verify` | Stream Analytics has no local emulator; the reference proves the cloud output |
| Late arrivals "allowed" | 2 s out of order, 5 s late; windows 6 s by default, 60 s from `./dev azure up` | Fits replays and real time |
| Managed identity | Managed identity to SQL; scoped keys for Event Hubs and Service Bus | Contributor cannot create role assignments |
| — | DAB anonymous read | Internal ingress only: reachable from the backend and engine in the same environment |
| — | Watermark marks from a second, arrival-ordered read of the hub; Azure SQL `INSTEAD OF INSERT` triggers turn them into `matchProgress` | Stream Analytics writes each output separately and append-only, so only SQL can tell when everything a watermark promises is committed |
| Stats on canonical events | SPADL actions converted from MA3 in ETL (`spadlActions`); stats, rules and context on SPADL | One standard action vocabulary for prompts, filters and formulas; MA3 is the provider-realistic stream |
| — | Trend indicators as read-time SQL procedures (`trendsAtSeq`, `trendSpellsAtSeq`, `trendMinutesAtSeq`) with a Python twin; thresholds and `enabled` in the `trendDefinitions` table, seeded from the trend experiment (`014`: momentum, fast breaks, contests, aggression and long-ball share disabled; pressure spells only alongside territory) | Exact at any snapshot, so a backlog equals live, and purge needs nothing new; no Stream Analytics change on Azure. Disabled trends stay computable for re-enabling with real data ([trends](components/trends.md)) |
| — | Demo seeds as an admin-API adapter (`local_stream/demo_seeds.py`, `DEMO_SEEDS=1` only): export a match's rows, restore them under a new matchId, then the worker reloads from SQL as after a restart | Mid-match demo starts with real history; core code never branches on a demo; absent in a production release |
| Job always on while deployed | Stream Analytics started by Event Hubs traffic and stopped after 30 quiet minutes (`stream_schedule.tf`, spend guard) | It bills while running; the demo build stays up for weeks |
| — | Tombstones on Azure: triggers drop rows of purged matches; the purge is the `etl-stream` image as a Container App (`ETL_ROLE=admin`, bearer token) | Stream Analytics cannot read SQL state per event (SQL reference data needs SQL logins; the server is Entra-only) |

## 3. Open items

*In short: what remains; production gaps live in [terraform decisions](../../terraform/docs/decisions.md).*

| Item | Notes |
| --- | --- |
| Late, duplicate and out-of-order injection | The seeder cannot inject them yet |
| Managed identity for messaging | Stream Analytics' Event Hubs input and Service Bus output, the seeder and consumers use scoped keys because Contributor cannot create role assignments; the registry uses admin credentials (no AcrPull grant) |
