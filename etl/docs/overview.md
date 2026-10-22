# Overview

> **In short:** match events stream into Event Hubs; one Stream Analytics job writes raw events, key events and per-minute statistics to serverless Azure SQL and sends notifications to Service Bus; Data API builder serves the tables over GraphQL. Implemented and tested; applied to Azure 22 Oct for the Azure test (demo acceptance pending).

| | |
| --- | --- |
| **Status** | Implemented · tested (unit, SQL on a disposable SQL Server, end-to-end verification, the shared local stack) · applied to Azure 22 Oct for the Azure test (demo acceptance pending) |
| **Demo** | Seed export/restore on the admin API, only with `DEMO_SEEDS=1` (implemented, SQL-tested, used for the four local seeds) |
| **Event format** | Opta MA1 (match info) and MA3 (events), labelled `synthetic: true` |
| **Runs on** | Event Hubs, Stream Analytics, Azure SQL serverless, Data API builder on Container Apps, Service Bus |
| **Writes** | SQL tables `matches`, `rawEvents`, `keyEvents`, `minuteStats`; Service Bus `match-notifications` |
| **Serves** | GraphQL (anonymous read; internal ingress only) |
| **Consumers** | Narrative engine, user backend |

## 1. What it does

*In short: four outputs from one stream.*

1. **History:** every event stored with typed columns and its full message.
2. **Key-event ledger:** goals, own goals, penalties awarded and missed, red cards and VAR overturns, with exact times.
3. **Statistics:** per-minute team deltas and a view of running totals as of any minute (goals, shots, passes, possession share, cards…).
4. **Notifications:** `MinuteClosed` when a match minute's window closes, `KeyEventDetected` for each key event, and `PeriodStarted` / `PeriodEnded`.

## 2. Inputs and outputs

*In short: one input stream; GraphQL and Service Bus out.*

| Direction | What | Contract |
| --- | --- | --- |
| In | Event Hubs `match-events`: MA1 first, then MA3 events, partition key `matchId` | [contracts](../contracts/README.md#input-event-hubs-match-events) |
| Out | GraphQL: `matches`, `rawEvents`, `keyEvents`, `minuteStats`, `matchStatsAsOfs` | [contracts](../contracts/README.md#output-1-graphql-data-api-builder-anonymous-read) |
| Out | Service Bus topic `match-notifications` | [contracts](../contracts/README.md#output-2-service-bus-topic-match-notifications) |
| Side | Event Hubs consumer group `user-backend` for live events | User backend reads the stream directly |

## 3. Status by area

*In short: built and verified against a Python reference; real-time speed needs a setting change.*

| Area | Status |
| --- | --- |
| Event contract, Opta codes | Implemented |
| Seeder (synthetic match, replay) | Implemented, tested; temporary until data generation provides matches |
| SQL tables and view | Tested locally and in Azure against the reference |
| Stream Analytics query | MA1/MA3 outputs were deployed (dev, deleted 2026-10-21); a 10x replay matched the reference for GraphQL and Service Bus. Multi-match outputs (POS, teams, players, canonical events, watermark marks), Azure SQL triggers and the purge API: implemented and tested against the reference and local stream; applied 22 Oct, Azure match run pending ([decisions](decisions.md#3-open-items)) |
| Data API builder | Applied 22 Oct (internal ingress, scales to zero) |
| Stream schedule (spend guard) | Applied 22 Oct: match events start the job, 30 quiet minutes stop it ([stream-analytics §6](components/stream-analytics.md#6-run-only-while-matches-play)) |
| Demo seeds (`DEMO_SEEDS=1`) | Implemented, SQL-tested, used for the local seeds; the 20′ seed recorded on Azure 22 Oct (HT, 60′, 85′ not yet) |
| Real-time (1x) match | `./dev azure up` sets `window_seconds = 60`; Azure run part of the pending acceptance |
| Local stream stand-in (`local_stream/`) | Implemented, unit- and SQL-tested, runs 1x replays in the local Docker stack; not deployed as a worker. Also MatchEvent v2, POS, watermarks, the stat catalogue, per-match purge and demo seeds (`DEMO_SEEDS=1`) ([local-stream](components/local-stream.md)) |

## 4. Glossary

*In short: the terms the code and docs use.*

| Term | Meaning |
| --- | --- |
| **MA1 / MA3** | Opta feed names: match info (teams, lineups) and match events |
| **Match clock** | `periodId`, `timeMin`, `timeSec`; first-half added time continues (46 = `45+2'`), the second half starts at 45:00 |
| **Qualifier** | Opta key/value detail on an event (9 penalty, 28 own goal, 55 related event, 901 VAR outcome…) |
| **Window** | Stream Analytics tumbling window; one window is one match minute (60 s / replay speed) |
| **Replay speed** | Match seconds per wall second; `--speed 10` gives 6-second minutes |
| **Reference pipeline** | The Python version of the job's rules, used as the expected result |
