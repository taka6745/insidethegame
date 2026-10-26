# Local integration

One Docker Compose stack runs the product and Microsoft emulators. This file owns the cross-service contracts.

![Local stack and Azure validation](development.svg)

## Run it

| Command | Purpose |
| --- | --- |
| `./dev doctor` | Docker preflight; allow 8–12 GB memory |
| `./dev up` / `./dev test` | Postgres + Cosmos checks |
| `ACCEPT_EULA=Y ./dev up azure` | Add messaging, SQL and ETL GraphQL |
| `ACCEPT_EULA=Y ./dev up backend` / `./dev test backend` | Whole product and integration checks |
| `./dev logs <service>` / `./dev status` / `./dev down` | Inspect / stop; database volumes survive |

Set `ACCEPT_EULA=Y` only after consenting to [Event Hubs](https://github.com/Azure/azure-event-hubs-emulator-installer/blob/main/EMULATOR_EULA.txt), [Service Bus](https://github.com/Azure/azure-service-bus-emulator-installer/blob/main/EMULATOR_EULA.txt) and [SQL Server](https://go.microsoft.com/fwlink/?LinkId=746388) terms. Default: `N`.

[Viewer](http://localhost:18020) · [Backend API](http://localhost:18000/docs) · [ETL GraphQL](http://localhost:15001/graphql) · [Engine GraphQL](http://localhost:18012/graphql). Ports bind to loopback. Model settings: ignored `.local/backend-llm.env` and `.local/decision.env`. Preserve `.local/` media and environments.

[Services and ports](compose.yaml) · [Defaults](env.defaults) · [Laptop connections](connections.env.example). Override locally with ignored `compose.override.yaml`. Checks verify application protocols, not Azure capacity or durability.

## Contracts

Services own their databases; never read another service's database. Keep emulator and Terraform names aligned. These are development contracts.

### 1. Identity and snapshots

Feed mints unique `matchId = {fixture}-{runId[:8]}`; MA1 introduces it. Canonical `seq` starts at 1 (`0` = MA1 only); MA3 and POS have separate consecutive counters. Snapshot `(matchId, seq)` bounds all derived data. Rows are immutable after the relevant watermark; SPADL/stat reads also wait for `spadlSeq`. Narratives carry `eventSeq`.

### 2. MatchEvent v2

Event Hubs `match-events`, partitioned by `matchId`. [Message model](../user-backend/backend/models/match_stream.py) with strict [event fields](../user-backend/backend/models/events.py); canonical events clock backend snapshots and ticker. Calculations consume SPADL, not this stream.

### 3. ETL GraphQL (DAB)

The only history/stat read path: [query surface](../etl/dab/dab-config.json). Read at or below watermarks; SPADL is final only when `finalSeq ≤ seq`. Backend queries are allow-listed; models never supply query text.

### 4. Stat catalogue

126 ids: 42 kinds × team/opponent/player. `executeStatsAtSeq(matchId, seq)` returns snapshot values; unsupported capabilities return `unavailable`. Goals include opponent own goals and subtract VAR reversals; saves count goalkeeper saves. [Golden values](../etl/tests/fixtures/catalogue-golden.json).

### 4b. Trend definitions

`executeTrendsAtSeq`, `executeTrendSpellsAtSeq`, `executeTrendMinutesAtSeq` serve configured indicators/windows. Disabled trends remain computable but cannot be claimed; pressure spells need territory evidence. Definitions and thresholds belong to ETL.

### 5. Purge

Every owner: `POST /admin/matches/purge {"match_id": …}` or `{"all": true}` → `200 {match_ids, purged}`; retry `503`. Tombstone before delete; ignore late messages; `all` sets a cutoff. Unknown ids still get tombstones. Preserve configuration. Order: feed → ETL → engine → backend. Azure ETL/engine require bearer admin tokens.

### 6. Live media (HLS)

Feed alone publishes `/hls/{matchId}/live.m3u8`; nginx exposes `/media/hls/{matchId}/`. Only segments ending by the run clock are visible; before playback/after purge: `404`. Playlists are uncached, segments immutable. Replays use published segments only; video requires MA1 capability.

### 7. Feed admin API (dev only)

Internal `feed:8000`, `/feed-api/` through developer auth. Recordings, runs and purge: [routes](../data-generation/feed/routes/http.py). Run limit returns `409`.

### 8. Backend product API

[Product routes](../user-backend/backend/routes/product.py): matches, profiles, prices and sessions. Session identity is viewer + profile + match. Questions use `min(latest, shown seq)`; audience changes select an enabled bucket. WebSocket close codes: `4404` match gone, `4001` replaced session, `1013` overload. Snapshots include cards, narratives, follows and clips. Comparison cards use labelled `sides` for both teams in one slot. `DELETE …/messages` clears Ask history/context and untracked offers; pins and follows remain.

Backend owns audience definitions, prompts, policy and model roles. Engine reads enabled `generation_targets`, frames each bucket, publishes over Service Bus; backend routes unchanged. History/reconnects use engine GraphQL. Viewers never enable buckets; questions never trigger shared narratives.

### 8b. Story follows

One follow per viewer per match (`409 follow_limit`); planner proposes, viewer confirms. Identical follows share a topic. Engine consumes subscription targets and publishes follow narratives/clips. [Routes](../user-backend/backend/routes/subscriptions.py) · [Messages](../narrative-engine/README.md#contracts).

### 8c. Cross-match reach and follow offers

Other matches use their own current positions; results carry `other_match` with teams/crests, not scores. Story answers may offer a Decision-1 follow; stat answers do not. A match's shared narrative never mentions another match.

### 8d. Replay playback (sting and slow motion)

Replay payloads carry timing, fades and the `builtin:league` sting. Published HLS clips play on a second player while live continues in a corner; `replay-timing` owns durations.

## Decisions and limits

Microsoft emulators keep SDKs aligned with Azure. Feed isolation preserves the provider boundary. Emulators lose messages on restart; start fresh feed runs after Event Hubs restarts. One local model shared across three matches can put narratives minutes behind.
