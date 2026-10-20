# Overview

> **In short:** a Python service that listens for the ETL's match notifications, keeps a compact shared memory of the match, and writes one to three sentence narratives for each active audience bucket when something happens. It is implemented, tested and deployed to the Azure dev environment.

| | |
| --- | --- |
| **Status** | Implemented · tested (66 tests) · deployed to dev as Container App `itg-narrative-dev-engine` |
| **Language** | Python 3.11, asyncio |
| **Runs on** | Azure Container Apps (one replica), Microsoft Foundry models via Microsoft Agent Framework |
| **Reads** | ETL GraphQL (events, key events, statistics); Service Bus `match-notifications` and `presence` |
| **Writes** | Cosmos DB (`checkpoints`, `contextBlocks`, `narratives`); Service Bus `narratives` |
| **Serves** | Narrative history GraphQL at `/graphql` |
| **Consumers** | User backend (BFF) |

## 1. What it does

*In short: shared match facts in, personalised commentary out, with model work shared wherever possible.*

During a live match the engine:

1. **Summarises every closed minute** in neutral language (minute summariser agent).
2. **Compresses older summaries** so the match memory stays small however long the match runs (context compressor agent).
3. **Writes narratives** for each active audience bucket when a narrative step is triggered (narrative author agent): a key event, ten quiet minutes, half time, full time, or a bucket gaining viewers.
4. **Stores, publishes and serves** each narrative: Cosmos DB first, then Service Bus, and the history over GraphQL.

Summaries and compression are done once per match and shared by every bucket; only the author runs per bucket. Viewer questions never trigger this workflow; they belong to the user backend.

## 2. Audience buckets

*In short: 12 buckets, `{support}:{level}`, and only buckets with viewers get narratives.*

| Support | Levels |
| --- | --- |
| `home`, `away`, `neutral` | `simple`, `casual`, `experienced`, `analyst` |

A bucket such as `away:analyst` is written for a fan of the away team with an analyst's vocabulary. The user backend reports how many viewers each bucket has (the presence message); when presence is missing or older than 3 minutes the engine writes for all 12.

## 3. Inputs and outputs

*In short: three inputs, three outputs, all defined in contracts.*

| Direction | What | Contract |
| --- | --- | --- |
| In | `MinuteClosed`, `KeyEventDetected`, `PeriodStarted`, `PeriodEnded` on Service Bus topic `match-notifications` | [ETL contracts](../../etl/contracts/README.md) |
| In | Match events, key-event ledger, statistics as of a minute, match info (ETL GraphQL) | [ETL contracts](../../etl/contracts/README.md) |
| In | Presence (viewer counts per bucket) on topic `presence` | [Engine contracts](../contracts/README.md#input-presence-proposed) |
| Out | One message per narrative on topic `narratives` | [Engine contracts](../contracts/README.md#output-2-service-bus-live-narratives) |
| Out | Narrative history and match state over GraphQL | [Engine contracts](../contracts/README.md#output-1-graphql-narrative-history-read-only) |
| Out | Traces and logs in Application Insights | [deployment.md](deployment.md#4-monitoring) |

## 4. Status by area

*In short: everything is built and running in dev; a 1x full-match run waits for the other services.*

| Area | Status |
| --- | --- |
| Core rules (clock, compression, triggers, orchestrator) | Implemented, tested |
| ETL GraphQL client | Implemented, tested against a fake DAB and the Azure dev DAB |
| Agents (Agent Framework on Foundry `gpt-5-mini`) | Implemented, tested (mocked API), run on full matches |
| Narrative history GraphQL | Implemented, tested, deployed |
| Service Bus and Cosmos DB | Implemented, deployed, verified on 10x replays (204/204 narratives delivered) |
| Monitoring (Application Insights, workbook) | Deployed |
| Presence from the user backend | Implemented in the engine; contract awaits the user backend |
| Real-time (1x) full match | Not yet run; planned once the other services are ready |

## 5. Glossary

*In short: the words the code and docs use.*

| Term | Meaning |
| --- | --- |
| **Match clock** | The ETL's Opta clock `(periodId, timeMin)`; `timeMin` is 0-based, first-half added time keeps counting (46 = `45+2'`), the second half restarts at 45. |
| **Horizon** | The latest `(clock, second)` an ETL notification has announced. The engine never reads ETL data past it. |
| **Context block** | A summary covering a span of the match: a minute, five minutes, or an earlier stretch. Replaced blocks are kept but marked `supersededBy`. |
| **Narrative step** | One trigger's worth of narratives, one per active bucket, sharing a `stepId`. |
| **Trigger** | Why a step runs: `keyEvent`, `scheduled`, `halfTime`, `fullTime`, `catchUp`. |
| **seq** | Per match and bucket narrative counter (1, 2, 3…) with no gaps, used for reconnects. |
| **Checkpoint** | The per-match Cosmos document holding progress, presence and the queue of pending steps. |
