# Overview

> **In short:** a Python service that listens for the ETL's match notifications, keeps a compact shared memory of the match, and writes one- or two-sentence narratives for each active audience bucket when something happens. It is implemented, tested and deployed to Azure.

| | |
| --- | --- |
| **Status** | Implemented · tested · deployed: Container App `itg-narrative-dev-engine` ([status](../../PLAN.md#11-azure-judge-build)) |
| **Language** | Python 3.11, asyncio |
| **Runs on** | Azure Container Apps (one replica); Microsoft Agent Framework on Azure AI Foundry: `gpt-6.1-sol` (`writer`, every agent at effort low) and Microsoft-Decision-1 (`decision-1`) |
| **Reads** | ETL GraphQL (SPADL actions, key events, the SPADL stat catalogue, MA3 facts outside SPADL); Service Bus `match-notifications`; user-backend audience targets and prompts |
| **Writes** | Cosmos DB (`checkpoints`, `contextBlocks`, `narratives`, `analyses`, `storylines`, follow decisions and narratives, `tombstones`); Service Bus `narratives` (also `FollowClip`, `MomentClip`) |
| **Serves** | Narrative history GraphQL at `/graphql` |
| **Consumers** | User backend (BFF) |

## 1. What it does

*In short: shared match facts in, personalised commentary out, with model work shared wherever possible.*

During a live match the engine:

1. **Summarises every closed minute** in neutral language (minute summariser agent).
2. **Compresses older summaries** so the match memory stays small however long the match runs (context compressor agent).
3. **Finds storylines** every five match minutes and at half and full time (match analyst agent): observations in its own words that must cite the ETL's trend numbers; ungrounded ones are dropped, and the rest open, develop and resolve storylines.
4. **Writes narratives** for each active audience bucket when a narrative step is triggered (narrative author agent): a key event, ten quiet minutes, a storyline turn, half time, full time, or a bucket being enabled. Each step advances one focus storyline, the same for every bucket.
5. **Answers story follows and flags clips**: one Decision-1 call per update decides which followed stories moved and which key events deserve a clip ([follows](components/follows.md)).
6. **Stores, publishes and serves** each narrative: Cosmos DB first, then Service Bus, and the history over GraphQL.

Summaries and compression are done once per match and shared by every bucket; only the author runs per bucket. Viewer questions never trigger this workflow; they belong to the user backend.

## 2. Audience buckets

*In short: the user backend's audience catalogue defines the buckets; only active ones get narratives.*

The engine reads the backend's `generation_targets` (for example team × fan style × length, each layer and option with a description) and writes only for those enabled in the backend's configuration (toggled in `/dev/`; there is no viewer presence). The descriptions and MA1 team names become the author's audience text. The service has no fallback: while the backend cannot answer, authoring waits and `/health` is 503. Only tests and devtools use the original 12 buckets (`home`/`away`/`neutral` × `simple`/`casual`/`experienced`/`analyst`).

## 3. Inputs and outputs

*In short: three inputs, three outputs, all defined in contracts.*

| Direction | What | Contract |
| --- | --- | --- |
| In | `MinuteClosed`, `KeyEventDetected`, `PeriodStarted`, `PeriodEnded` on Service Bus topic `match-notifications` | [ETL contracts](../../etl/contracts/README.md) |
| In | SPADL actions, key-event ledger, catalogue statistics at a canonical seq, match info (ETL GraphQL) | [ETL contracts](../../etl/contracts/README.md) |
| In | Active buckets and prompt templates from the user backend (`audience-config`, `narrative-prompts`) | [Engine contracts](../contracts/README.md#inputs-from-the-user-backend) |
| Out | One message per narrative on topic `narratives`; `FollowClip` and `MomentClip` for moment clips | [Engine contracts](../contracts/README.md#output-2-service-bus-live-narratives) |
| Out | Narrative history and match state over GraphQL | [Engine contracts](../contracts/README.md#output-1-graphql-narrative-history-read-only) |
| Out | Traces and logs in Application Insights | [deployment.md](deployment.md#4-monitoring) |

## 4. Status by area

*In short: everything is built, tested and deployed; grounding quality has not yet been sampled on Azure.*

| Area | Status |
| --- | --- |
| Core rules (clock, compression, triggers, orchestrator) | Implemented, tested |
| ETL GraphQL client | Implemented, tested against a fake DAB and the Azure dev DAB |
| Agents (Agent Framework on Azure AI Foundry) | Implemented, tested (mocked API), run on full matches |
| Narrative history GraphQL | Implemented, tested; internal ingress on Azure |
| Service Bus and Cosmos DB | Implemented, verified in Azure on 10x replays (204/204 narratives delivered) |
| Monitoring (Application Insights, workbook) | Deployed |
| Targets and prompts from the user backend | Implemented, tested (mocked HTTP); runs in the local stack as `narrative-live` |
| Concurrent matches: one orchestrator per matchId, a global model gate (summaries first, per-match fairness), purge with Cosmos tombstones (`POST /admin/matches/purge`), `tier` on context blocks, `eventSeq` on narratives | Implemented, tested (router, gate, memory store) |
| Local stack (`./dev up backend`): ETL `etl-stream` stand-in → SQL + DAB → `narrative-live` → backend → viewer | Implemented, run on live replays (local only) |
| Story follows (followed topics, Decision-1 triggers, follow narratives, GraphQL) and decision-model claim checks | Implemented, tested (fakes over the Riverton Rovers–Forgeham United recording); run on the local stack and Azure |
| Moment clips: `FollowClip`, clip-on topics, `MomentClip` for shared key-event narratives | Implemented, tested; deployed (a capture card played as a replay on Azure) |
| Demo seeds: export/restore under `DEMO_SEEDS=1` | Implemented, tested; deployed (seeded 60′ start in about 8 s) |
| Real-time (1x) three-match run | Run locally and on Azure (engine lag about half a match minute) |

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
| **Checkpoint** | The per-match Cosmos document holding progress, the last targets and the queue of pending steps. |
