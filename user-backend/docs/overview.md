# Overview

> **In short:** a multi-match FastAPI service. Each match arrives on Event Hubs (MA1, then canonical MatchEvent v2, which clocks its snapshots); custom rules, questions and replays use SPADL actions read from ETL GraphQL at a `(matchId, seq)` snapshot, together with ETL's standard stats, teams and players. The backend serves one shared projection per match to viewers over WebSocket; narratives come from the narrative engine; footage is the feed's HLS over HTTP. It also serves story follows with moment clips, cross-game reach and (demo only) seed restore.

| | |
| --- | --- |
| **Status** | Implemented · tested against real Postgres and contract doubles · deployed on Azure ([status](../../PLAN.md#11-azure-judge-build)) |
| **Runs on** | Python 3.12, FastAPI, Microsoft Agent Framework, PostgreSQL (Accounts and Match App databases) |
| **Target** | Azure Container Apps, Azure Database for PostgreSQL Flexible Server, Azure AI Foundry models ([deployment](deployment.md)) |
| **Reads** | Event Hubs `match-events` (group `user-backend`), ETL GraphQL (Data API builder), narrative GraphQL, Service Bus `narratives`, feed HLS |
| **Serves** | Viewer API and WebSocket (`/product`), audience and prompt APIs for the engine, developer APIs (`/dev`, `/lab`) |
| **Owns** | Demo profiles, viewer sessions, chat, pins, custom calculations, audience templates, narrative prompts, backend config tables (including the model per role) |

## 1. What it does

*In short: seven jobs for the viewer, none of them narrative writing.*

1. **Follow matches.** One `LiveMatch` per `matchId`, rebuilt from its received events and saved calculations after a restart; SPADL actions are read again from ETL.
2. **Show cards and narratives.** One projection per match composes each viewer's five stat cards (ETL values) and the narratives for the viewer's chosen audience bucket (team × style × length); the viewer may change bucket at any time.
3. **Answer questions.** A router agent classifies the request; values come from ETL rows or deterministic rules, never model prose ([agents](components/agents.md)).
4. **Custom stats.** A goal agent and deterministic compiler turn a request into a bounded rule over SPADL actions (type, result, body part, zones, locations); equivalent rules share one calculation per match; Track pins it as a live card.
5. **Replays.** A replay agent picks evidence; code cuts clips from the feed's published HLS; each replay carries `playback` (sting transitions, slow motion).
6. **Follows and clips.** One story follow per viewer; the engine's `FollowClip` and `MomentClip` messages become the follow's and the bucket's moment playlists ([services §10](components/services.md#10-clips-cross-game-and-follow-offers)).
7. **Cross-game.** Questions, pins and follows may name another live match, read at that match's own position and marked with its header; a story answer may get a "Follow this story?" offer.

Questions never trigger narrative generation. Audience definitions belong to this service; the narrative engine reads them and writes the bucket wording.

## 2. Inputs and outputs

*In short: brokers and GraphQL in; HTTP and WebSocket out.*

| Direction | What | Contract |
| --- | --- | --- |
| In | Event Hubs `match-events`: MA1 and MatchEvent v2 (clock, periods, ticker; MA3 and POS are ETL's) | [contracts §2](../../local/contracts/README.md#2-matchevent-v2) |
| In | ETL GraphQL: `matches`, `matchWatermarks` (`seq`, `spadlSeq`), `executeStatsAtSeq`, `spadlActions`, `rawEvents` (MA3 cards, goals, VAR) | [contracts §3](../../local/contracts/README.md#3-etl-graphql-dab) |
| In | Narrative engine: Service Bus `narratives`, GraphQL `contextBlocks` | [engine contracts](../../narrative-engine/contracts/README.md) |
| In | Feed HLS playlist over HTTP (`FEED_HLS_BASE`) | [contracts §6](../../local/contracts/README.md#6-live-media-hls) |
| Out | Viewer API and WebSocket under `/product/matches/{matchId}` | [contracts §8](../../local/contracts/README.md#8-backend-product-api) |
| Out | `GET /matches/{matchId}/audience-config`, `GET /narrative-prompts`, `GET /storyline-policy`, `GET /model-roles` for the engine | [routes](components/routes.md#3-audience-configuration) |

## 3. Status by area

*In short: everything below runs locally and on Azure; multi-replica delivery is not built.*

| Area | Status |
| --- | --- |
| Stream ingestion, restart, purge per match | Implemented, tested |
| Seq-gap detection and recovery | Implemented, unit-tested; ETL's DAB exposes `canonicalEvents` (query checked against DAB 2.1.5), recovery not yet exercised live |
| Projections, cards, narratives, takeover | Implemented, tested |
| Audiences (config-only enabled buckets) | Implemented, tested |
| Questions, custom stats, replays on SPADL | Implemented, tested with scripted model decisions; live-model golden sets in [benchmarks](components/benchmarks.md) |
| Saved-rule, prompt and replay-timing migrations to SPADL (`020`–`022`) | Implemented, tested on Postgres |
| Config tables, prompts, profiles editors, model per role | Implemented, tested |
| Story follows, follow clips, capture cards, key-event clips | Implemented, tested on Postgres |
| Cross-game, follow offer | Implemented, tested |
| Demo seeds (`DEMO_SEEDS=1` only) | Implemented, tested (export, refusals, restore, adopt) |
| Azure deployment | Deployed with Terraform ([deployment](deployment.md)) |
| Multi-replica delivery | Not built: one process per deployment ([architecture §6](architecture.md#6-scaling-boundary)) |
| Isolated arbitrary-code executor | Not built; custom stats compile to a bounded rule DSL instead |

## 4. Glossary

*In short: the words the other pages use.*

| Term | Meaning |
| --- | --- |
| Snapshot | `(matchId, seq)`, id `{matchId}:{seq}`; `seq = min(ETL watermark, spadlSeq, events received)` |
| SPADL action | One on-ball action (type, result, body part, zones, locations), converted by ETL from MA3; final once served |
| Projection | The shared per-match state (stats, events, narratives, custom values) a viewer's view is composed from |
| Bucket | One combination of audience options (team, style, length; e.g. `home:analytical`); narratives are written per enabled bucket |
| Template | A fixture's audience configuration (or the `default` one) |
| Viewer | One browser (`viewer_id`); a session belongs to one (viewer, profile, match) |
| Pin / Track | A viewer's live card for a standard stat or a shared custom calculation |
| Gap | A missing `seq` while later events have arrived |
