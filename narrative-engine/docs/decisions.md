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
| Compression may span half time | Blocks never span half time; a finished half collapses into one block | Agreed in the [implementation plan](design/implementation-plan.md) |
| Half-time step optional | Always written | Viewers expect it |
| Presence as per-bucket deltas | The user backend's `generation_targets` (buckets enabled in its config; no viewer presence), polled with an ETag; a newly enabled bucket is caught up at once | The backend owns audience definitions (AGENTS.md); no stale fallback to all buckets |
| A scheduled step after every ten quiet minutes | None on a period's last minute or in stoppage time; that period's last minute is not compressed separately | The half-time or full-time step follows within minutes; over the three GRF recordings with 12 buckets it saves 4 compressions in one and 12 author calls in another, deterministically (live and backlog alike) |
| Service exits when Service Bus drops | The listener reconnects in-process with backoff | No container restart, no lost in-memory workers |
| User backend reads Cosmos directly | The engine serves history over GraphQL | One query style, testable offline, computed fields |
| Topic `narrative-created` | Topic `narratives` carrying the whole narrative | Consumers deduplicate and fill gaps without a second read |
| Container `matches` | `checkpoints` | It also holds the step queue |
| Hold a message while working | Record and complete, then work in the background | Long model calls lost Service Bus locks |
| One Foundry writing model | One deployment `writer` (`gpt-6.1-sol`), reasoning effort per agent; models swappable per agent | `gpt-6.1-sol` has no `minimal` effort, so every role runs at `low` |
| Narratives react to the latest minute | A match analyst every 5 minutes (and at half and full time) keeps storylines; each step advances one focus storyline chosen in Python and shared by every bucket | Narratives are storylines through the game, not last-minute commentary |
| Patterns from a fixed list | The analyst names patterns in its own words; the validator checks only grounding (cited values equal the ETL's trend rows, cover the team, and the text uses only their numbers and names) | Don't hard-code or lead the witness |
| Ungrounded claims dropped silently | One repair turn with the check's reasons per rejected analyst item and author excerpt, then drop and log; the author's numbers, names and causal claims are checked (claims by Microsoft-Decision-1, thresholds in the policy's `claims`) | Ungrounded text reached viewers; one repair recovers most of it ([evidence](components/analysis.md#4-grounding-evidence)) |
| Storyline constants in code | The backend's `storyline-policy` config (`GET /storyline-policy`, ETag, `/dev/config`), read like the prompts with no fallback; code keeps only the reply schema, the language checks and the trend windows' minute marks | No magic numbers; every tunable editable per deployment |
| Grounding rules in the prompts | Prompts describe inputs and outputs only; the validators enforce grounding and their reasons drive the repair turn | don't hard-code rules, phrase lists or example conclusions into prompts |
| Analysis offset per match | Every match analyses at its own minutes 5, 10, 15 … | Matches stay unaware of each other; the demo staggers kickoffs |
| Author stat-selection instructions | Not produced by the engine | Moved to the user backend |
| Story follows: one decision per subscription per update | One batched Decision-1 call per update for every topic it involves (entity prefilter, light gap with a pivotal bypass, novelty question); decisions stored and pinned before authoring | Shared topics generate once; a backlog or restart never re-asks; the limit is requests per minute, not questions |
| Followed stories listed in the decision state | Subscription-decision v2: the shared state has no viewer text; each topic's focus is quoted only in its own questions, with positional keys | One viewer's free text never reaches another viewer's judgement or the shared prompt |
| Analyst limits and a result phrase list in code | Analyst v3 fills its limits from the storyline policy (`prompt_limits`), the validator reads the same section; a result before full time is a third `claims` question (`result`) in the same batched decision call | No magic numbers, no phrase lists |
| Clips as a Phase 2 resolver | The engine flags clip-worthy key events in the follow decision call (clip `Score`, or clip-on kinds in `clips.always_for`) and sends `FollowClip`; shared key-event steps send `MomentClip`; the backend cuts the clip | No extra model call; a narrative dropped as ungrounded keeps its clip; common events never clip |
| Mid-match starts by replaying from kick-off | Recorded seeds restored under a new matchId through a demo-only adapter (`DEMO_SEEDS=1`), then the match continues live | Seconds instead of minutes to a rich story so far; core code never branches on a demo, and a production release has no seed routes |
| Managed identity everywhere, Key Vault | Managed identity for Cosmos; scoped keys as Container App secrets elsewhere | Contributor cannot create role assignments |
| Leader election for the scheduler | One replica | Enough for the demo |
| Newest run supersedes older runs (`MATCH_IDS`) | Every matchId runs; lifecycle from MA1, the final `PeriodEnded` and tombstones | Several matches at once |
| Fallback to 12 buckets and shipped prompts | None in the service: pause and `/health` 503 | No hard-coded data on the live path |
| Raw MA3 events and `matchStatsAsOfs` in prompts | SPADL actions (`spadlActions`, settled up to the step's canonical seq) and the SPADL stat catalogue (`executeStatsAtSeq`); key events, yellow cards, substitutions and period markers stay outside SPADL; the score comes from `keyEvents`; prompts v4/v2 add a SPADL glossary | One action vocabulary across ETL, backend and engine; seq bounds keep backlog equal to live |

## 3. Open items

*In short: what still needs doing or agreeing.*

| Item | Owner | Notes |
| --- | --- | --- |
| Throughput under several matches | Engine | One shared model: see [architecture §6](architecture.md#6-guarantees-and-limits). Backlogs drain without loss; raise `MODEL_CONCURRENCY` or use a faster author model on Azure AI Foundry |
| Grounding on Azure | Engine | Not yet sampled on Azure with `gpt-6.1-sol` |
| Odd phrasing ("Half an hour? Sorry—20 minutes") | Engine | Prompt or model; try with a stronger author model |
| ETL subscription backlog | ETL + engine | Unread notifications expire after a day (topic TTL); purge old matches (`POST /admin/matches/purge`, `{"all": true}` sets a cut-off) before a demo |

## 4. Production gaps

*In short: security upgrades blocked by the trial account's role, recorded in [terraform decisions](../../terraform/docs/decisions.md).*

- Managed identity for Service Bus, Foundry ("Cognitive Services OpenAI User") and the registry (AcrPull), then remove keys and ACR admin.
- Authenticate the history API's callers (it is already on internal ingress, reachable only inside the Container Apps environment).
