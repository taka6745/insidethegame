# Decisions

> **In short:** where the built engine follows the [original design](design/narrative-generation-engine.md), where it differs and why, and what is left. When the design and the ETL contracts disagree, the ETL contracts win.

| | |
| --- | --- |
| **Design** | [design/narrative-generation-engine.md](design/narrative-generation-engine.md), [design/design-notes.md](design/design-notes.md) |
| **Decision log** | [design/implementation-plan.md](design/implementation-plan.md) (phase by phase) |

## 1. Kept from the design

*In short: the core idea is unchanged.*

- One shared minute summariser and compressor; a personal author per bucket.
- Driven by `MinuteClosed`, with no local timer.
- The §5.3 compression rules; active blocks always cover the whole match.
- Key events trigger the author at once (no debounce), so corrections get their own step.
- Author runs serialised per bucket, parallel across buckets.
- Scheduled step after ten quiet match minutes; catch-up steps for new buckets.
- Stateless agent calls built from stored data; deterministic IDs; save before publish.
- Cosmos DB serverless, partitioned by `/matchId`; Microsoft Agent Framework on Foundry.

## 2. Changed from the design

*In short: each change has a reason recorded here.*

| Design | Built | Why |
| --- | --- | --- |
| Clock `(period, minute, addedMinute)` | Opta `(periodId, timeMin)` with broadcast labels | The ETL contract |
| Message shapes in design §9 | The ETL's actual messages | The ETL contract |
| Compression may span half time | Blocks never span half time; a finished half collapses into one block | Agreed 18 Oct |
| Half-time step optional | Always written | Viewers expect it |
| Presence as per-bucket deltas | Full counts plus a 60 s heartbeat, stale after 3 min, then all 12 | A lost delta cannot leave a bucket stuck |
| User backend reads Cosmos directly | The engine serves history over GraphQL | One query style, testable offline, computed fields |
| Topic `narrative-created` | Topic `narratives` carrying the whole narrative | Consumers deduplicate and fill gaps without a second read |
| Container `matches` | `checkpoints` | It also holds the step queue |
| Hold a message while working | Record and complete, then work in the background | Long model calls lost Service Bus locks (19 Oct) |
| Small and strong Foundry deployments | One `gpt-5-mini`, reasoning effort per agent; models swappable per agent | `gpt-4.1-mini` is Legacy; effort gives the same split |
| Author stat-selection instructions | Not produced by the engine | Moved to the user backend (20 Oct) |
| Managed identity everywhere, Key Vault | Managed identity for Cosmos; scoped keys as Container App secrets elsewhere | Contributor cannot create role assignments |
| Leader election for the scheduler | One replica | Enough for the demo |

## 3. Open items

*In short: what still needs doing or agreeing.*

| Item | Owner | Notes |
| --- | --- | --- |
| Reconcile with the demo stand-in's contract | User backend + engine | The local stack and backend use [`narrative_demo/`](components/narrative-demo.md)'s `MatchSnapshotReady` → `BucketNarratives` boundary and the backend's `generation_targets` API; the engine uses the Azure ETL's per-minute notifications, one message per narrative and presence. Agree one contract, then swap the stand-in for the engine |
| Presence contract | User backend + engine | [Proposed format](../contracts/README.md#input-presence-proposed) is implemented in the engine; superseded if `generation_targets` is adopted |
| Real-time (1x) full match | Both | Needs the ETL window at 60 s and the other services ready |
| Second-half live check on Agent Framework | Engine | The 20 Oct run stopped at half time (local memory) |
| Odd phrasing ("Half an hour? Sorry—20 minutes") | Engine | Prompt or model; try with a stronger author model |
| ETL subscription backlog | ETL + engine | No TTL on `narrative-engine`; keep `match_ids` set or purge before a match |

## 4. LATER (needs Owner or RBAC Administrator)

*In short: security upgrades blocked by the trial account's role; search `LATER` in the code.*

- Managed identity for Service Bus, Foundry ("Cognitive Services OpenAI User") and the registry (AcrPull), then remove keys and ACR admin.
- Restrict the history API to the user backend instead of anonymous read.
