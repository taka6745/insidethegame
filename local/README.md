# Local integration

One Docker Compose project (`itg-local`) runs every service, the Microsoft emulators and the demo operator; `./dev` starts and checks it. This folder also holds the **contracts**: the only places where services meet. Only demo control is deployed from here; the emulators, the ETL stand-in worker and the local model never are.

![Local development and Azure validation](development.svg)

```text
feed ─ MA1, MA3, POS, MatchEvent v2 → Event Hubs ─┬→ backend (received events)
  └─ played HLS ← nginx /media/hls/{matchId}/      └→ etl-stream → SQL + etl-dab GraphQL → backend, engine
                                                         └→ Service Bus match-notifications → narrative-live
                         backend ← Service Bus narratives ← narrative engine (targets + prompts from backend)
                          viewer ─ /demo-api/ → demo control → feed, ETL, engine, backend
```

## Run it

| Command | Does |
| --- | --- |
| `./dev doctor` | Docker preflight |
| `./dev up` / `./dev test` | Postgres + Cosmos emulator, then checks |
| `ACCEPT_EULA=Y ./dev up azure` | + Event Hubs, Service Bus, SQL Server, ETL GraphQL (DAB) |
| `ACCEPT_EULA=Y ./dev up backend` | The whole product and demo control, then backend tests and pipeline probes |
| `./dev demo start [fixture…]` / `./dev demo purge` | Purge every owner (feed → ETL → engine → backend), then start feed runs at the next whole minute; configuration stays |
| `./dev logs <service>` / `./dev status` / `./dev down` | Logs; status; stop, keeping SQL/Postgres volumes |
| `python3 -m pytest -q local/test_demo_control.py` | Demo control unit tests (fake feed and owners) |

`ACCEPT_EULA=Y` accepts the [Event Hubs](https://github.com/Azure/azure-event-hubs-emulator-installer/blob/main/EMULATOR_EULA.txt), [Service Bus](https://github.com/Azure/azure-service-bus-emulator-installer/blob/main/EMULATOR_EULA.txt) and [SQL Server](https://go.microsoft.com/fwlink/?LinkId=746388) terms; the default is `N`. Needs 8–12 GB of Docker memory (SQL Server and DAB run as `linux/amd64`); no Azure account. Only loopback ports are published. Viewer `http://localhost:18020/` (`/lab/`, `/dev/`), backend `http://localhost:18000/docs`, ETL GraphQL `http://localhost:15001/graphql`, feed `http://localhost:18030`, engine GraphQL `http://localhost:18012/graphql`. Inside Docker: `postgres:5432`, `feed:8000`, `etl-stream:8000`, `etl-dab:5000`, `narrative-live:8000`, `backend:8000`, `cosmos:8081`, `eventhubs:5672`, `servicebus:5672`, `sql:1433`. The local model comes from the ignored `.local/backend-llm.env`, Decision-1 from `.local/decision.env` (never print either).

| File | Holds |
| --- | --- |
| `compose.yaml`, `env.defaults` | Every service, profile, health check and port; read with `--env-file local/env.defaults`. Personal changes in the ignored `compose.override.yaml` |
| `config/eventhubs.json`, `config/servicebus.json` | Emulator hubs, consumer groups, topics, subscriptions (same names as Terraform) |
| `sql/postgres.sql`, `settings.py` | Creates `matchapp` on a fresh volume; Docker-network endpoints and public emulator keys for the checks |
| `check.py`, `broker_check.py`, `backend_broker_check.py`, `etl_stream_check.py`, `broker_ready.py` | The checks: database round trips; read-only ETL GraphQL and broker send/receive; a synthetic probe match through Event Hubs → `etl-stream` → SQL → DAB → backend, then purged from every owner |
| `demo_control.py`, `demo-control.Dockerfile`, `test_demo_control.py` | The demo operator |
| `connections.env.example`, `verify.env.example`, `no-media/` | Running a service on the laptop; a second stack beside `itg-local`; empty media root |

`./dev` hard-links each `.local/grf-demo-{fixture}-90/hls/` into `.local/media/{fixture}/hls/` and mounts that one root (`ITG_MEDIA_ROOT`) into the feed only; a fixture without media plays without video. The checks prove application data protocols, not Azure provisioning, durability or capacity.

## Demo control

The demo's operator between the simulated provider and our services: not a product service, off in a release build. Public `/demo-api/{start,cancel,skip,state,status}` through nginx, no login (§7a below). Owners: feed, ETL, engine, backend (base URL + optional admin token); purge order feed first. One replica, so start and cancel never interleave.

```text
viewer ─ /demo-api/… ─▶ demo-control ─┬▶ feed  /demo/start · /demo/skip · /runs/{id}/release
                                      ├▶ ETL, engine, backend  /admin/matches/{purge,export,restore}
                                      └▶ /seeds/{seed_id}/manifest.json + {owner}/{fixture}.json
```

| Action | What happens |
| --- | --- |
| Start (kickoff) | Purge the previous demo's finished matches; the feed starts the three fixtures, main game first, staggered |
| Start (20′, HT, 60′, 85′) | The feed creates waiting runs; each owner restores the seed under the new ids (ETL, backend, then engine; an owner's `503` retried 3 times); runs are released main game first; any failure purges them (`503`); a stale seed is `409` |
| Skip ahead | Every run's clock moves on by the same minutes; matchIds stay, so follows and sessions carry on |
| Cancel | Purge every match from every owner, feed first |
| State / Status | Start points (`ready` only with a fitting seed), live runs, `live_from`, skip targets; seven readiness stages (feed, Event Hubs, ETL, Service Bus, engine, backend, viewer), also waking apps scaled to zero |

Start and cancel answer `202` and run one after another under one lock; the viewer polls `/state`. While a demo is live a keep-warm loop pings every owner (`DEMO_KEEP_WARM_SECONDS` 60) so nothing scales to zero mid-match; finished runs are swept after `DEMO_SWEEP_GRACE_SECONDS` (900); on Azure Start also calls the spend guard's stream-start webhook (`DEMO_STREAM_START_URL`). Settings: `DEMO_FEED_URL`, `ETL_ADMIN_URL`, `ENGINE_ADMIN_URL`, `BACKEND_URL`, `ETL_ADMIN_TOKEN`, `ENGINE_ADMIN_TOKEN`, `DEMO_SEED_ROOT` (`/seeds`), purge/restore/capture timeouts.

**Seeds.** A seed is recorded on the pipeline, never reconstructed, so nothing past its point exists. Seed routes exist only with `DEMO_SEEDS=1` (local compose and the demo build), in one demo adapter per owner; core services never branch on a demo.

```sh
docker compose -p itg-local exec demo-control python /checks/demo_control.py record 20             # held runs from kickoff: nothing at or past 20′ is sent
docker compose -p itg-local exec demo-control python /checks/demo_control.py capture 20            # wait until every owner settled, export, name the seed, purge
docker compose -p itg-local exec demo-control python /checks/demo_control.py record ht --from 20   # chain HT, 60, 85
docker compose -p itg-local exec demo-control python /checks/demo_control.py adopt <seed-id>       # a seed copied from another stack
```

| Owner | Restores | Not seeded |
| --- | --- | --- |
| feed | Run resumes at the point, no MA1 | — |
| ETL | Every match table; the worker reloads from SQL | — |
| engine | Checkpoint, context blocks, narratives, analyses, storylines | Viewers' follow decisions and narratives |
| backend | Received match and events, gaps, audience catalogue, engine narratives and clips | Sessions, follows, questions, calculations |

Layout: `manifest.json` (format 2, point, each owner's schema fingerprint, per fixture the source match, seq and video second) and `{owner}/{fixture}.json`; `.local/seeds/` locally, an Azure Files share on Azure, both at `/seeds`. Restore rewrites each fixture to the new matchId and runId and is bounded by the seed's seq; each owner refuses (`409`) another schema, a known or tombstoned match, rows of another match and rows past the seq. Don't record during a demo. On Azure demo control is an internal Container App (`terraform/demo_control.tf`, min 1 / max 1 replica, 1 vCPU / 2 GiB); record seeds with `az containerapp exec … python /checks/demo_control.py record|capture`.

## Contracts

Each service owns its database and API; services meet only here. Keep the same names in emulator config and Terraform; agree changes here before changing producers and consumers. Development contracts, not a final production schema.

### 1. Identity and snapshots

- `matchId` = `{fixture}-{first 8 hex of runId}`, minted only by the feed (`POST /runs`), never reused. Owners learn about a match from its MA1. Contestant ids are stable club slugs (`riverton`, `forgeham`); MA1 `contestant[].knownNames` lists other names fans use.
- `seq` counts canonical events 1, 2, 3… per match with no gaps, in send order (`seq 0` = MA1 only). MA3 `seq` and POS `sampleId` count the same way; the Azure watermark relies on all three.
- Snapshot = `(matchId, seq)`, id `{matchId}:{seq}`. Everything derived cites it: `statsAtSeq` rows, cards, projections, answers. Engine narratives add `eventSeq`. Data at `s` is immutable once `matchWatermarks.seq ≥ s` (SPADL and stats: `spadlSeq ≥ s`) and unreachable before.

### 2. MatchEvent v2

The canonical contact-level event on Event Hubs `match-events` (partition key `matchId`), one per recording event with `seq`; it clocks the backend's snapshots and feeds the ticker. Fields follow the [Opta-style event contract](../data-generation/README.md#event-contract); strict, extra fields forbidden. Custom rules and agents read SPADL (§3), not this.

### 3. ETL GraphQL (DAB)

The only match-data read path. `matches` (+ `matchTeams`, `matchPlayers`), `matchWatermarks` (`seq`, `spadlSeq`, status), `canonicalEvents`, `possessionSamples`, `rawEvents` (indexed `eventSeq`), `keyEvents`, `spadlActions` (final once `finalSeq ≤ seq`), `executeStatsAtSeq(matchId, seq)`, the trend procedures (§4b), `statDefinitions`, `trendDefinitions`. Read at `s` only when `s ≤` the watermark. The backend uses allow-listed queries; the model never supplies query text.

### 4. Stat catalogue

`statDefinitions`: 42 kinds × 3 scopes (team, opponent, player) = 126 frozen stat ids, every value counted over SPADL actions (plus MA3 cards and VAR rows, POS possession). `executeStatsAtSeq` returns one row per (stat, contestant) at a snapshot; metrics the MA1 capabilities don't cover are `unavailable`. `shots_saved` counts real goalkeeper saves; `goals` includes own goals by the opponent and subtracts VAR overturns. Full-time values for the shipped recordings are pinned in `etl/tests/fixtures/catalogue-golden.json`.

### 4b. Trend definitions

`trendDefinitions`: per indicator a label, formula id, thresholds and `enabled`, seeded by migration and editable; `executeTrendsAtSeq` (indicator × team × window: last 5, last 15, half, match), `executeTrendSpellsAtSeq` (territory and pressure spells), `executeTrendMinutesAtSeq` (minute rows). Disabled trends (momentum, fast breaks, contests, aggression, long-ball share) are computed but may not be claimed; pressure spells serve only alongside territory.

### 5. Purge

`POST /admin/matches/purge {"match_id": …}` or `{"all": true}` on every owner → `200 {"match_ids": […], "purged": {…}}`; idempotent; `503` means retry. Tombstone first, then delete: messages for a tombstoned match are settled and dropped, never re-creating rows; `all` also records a cut-off so an older MA1 is dropped. Unknown id: `200`, zero counts, tombstone written. Only match data goes; configuration stays. Callers purge feed, ETL, engine, backend in that order; on Azure the ETL and engine purges need `Authorization: Bearer <token>`, added by nginx behind `/dev/` basic auth.

### 6. Live media (HLS)

Only the feed writes `live-media/{matchId}/` and serves `/hls/{matchId}/live.m3u8`; nginx proxies `/media/hls/{matchId}/`; the backend reads it via `FEED_HLS_BASE`. A segment is listed only once its end ≤ the run's clock; `404` before the first segment and after a purge; playlist `no-cache`, segments immutable; no MP4, no seek. Present only when MA1 `capabilities.video` is true; replay clips reference published segments only.

### 7. Feed admin API (dev only)

Internal `feed:8000`, proxied as `/feed-api/` only for `/dev/`: `GET /recordings`, `POST /runs {fixture, kickoff: "next-minute"}`, `GET /runs`, `POST /admin/matches/purge`, `GET`/`PUT /demo` (settings), `POST /demo/start {point}`; with `DEMO_SEEDS=1` also `POST /runs/{id}/release` and `POST /demo/skip {target}`. Runs past `max_active_runs` are `409`.

### 7a. Demo control (public)

`/demo-api/start {point}`, `/cancel`, `/skip {target}` (POST; one shared limit 10/min, burst 5), `/state`, `/status` (GET; per client 40/s, burst 200); over the limit `429`; `202` for start and cancel, then poll `/state`. Without a reachable demo control nginx answers `502` and the viewer hides the controls.

### 8. Backend product API

`GET /product/matches` (live, then scheduled, then finished: `match_id`, `fixture`, `status`, `scheduled_kickoff`, `seq`, `period`, `clock_seconds`, `teams[]` with score and branding, `video.hls`); `GET /product/profiles`; `GET /product/prices` (`{input, output}` US$ per million tokens, ETag). `M` = `/product/matches/{matchId}` (the frontend's `/viewer-api/`): `POST M/sessions {profile_id, viewer_id}` (one session per viewer, profile and match; takes over that viewer's previous socket; `404 match_not_started` before MA1), `GET M/sessions/{token}`, `PUT …/audience {bucket_id}` (`422 audience_unavailable`), `POST …/messages {prompt, request_id, seq?}` (answered at `min(latest, seq)`), `GET …/turns/{turn}/replay/{page}`, `POST …/offers/{offer}/track` (`409 cards_full`), `DELETE …/pins/{calculation}`, `WS …/live` (snapshots, updates, 20 s heartbeats; close `4404` match gone, `4001` session replaced, `1013` overloaded). Snapshots carry `version`, `projection_epoch`, `match`, `events`, `cards`, `narratives` (the viewer's bucket only), `audience`, `audience_buckets`, follow and clip playlists, `other_match`. Pivotal key moments (goals, red cards, penalties, VAR, period boundaries) show for every viewer as `key_moments`.

**Audiences are configuration only.** Each fixture's template (or `default`) defines layers, options (`id`, viewer `label` with `{home}`/`{away}`, model-facing `description`, optional `team`) and buckets with an `enabled` flag, edited in `/dev/`. The engine's `GET /matches/{matchId}/audience-config` returns `generation_targets` = the enabled buckets; prompts (`GET /narrative-prompts`), the storyline policy (`GET /storyline-policy`) and model roles (`GET /model-roles`) are global. Viewers never enable buckets; there is no presence.

### 8b. Story follows

`GET/POST M/sessions/{token}/follows`, `DELETE …/follows/{id}` (one follow per viewer per match, `409 follow_limit`; may target another live match; `429 rate_limited` past the tunables); `GET …/follow/suggestions?seq=`, `POST …/follow/messages` (the planner proposes, the viewer confirms). Identical follows share a topic; the engine reads `GET /matches/{id}/subscription-targets` (topics, their follower buckets, the follow and clip tunables, ETag) and publishes `kind: subscription` narratives, `FollowClip` and `MomentClip` ([engine contracts](../narrative-engine/README.md#contracts)). Followers see their story in place of the shared insights; "Stop following" restores them.

### 8c. Cross-match reach and follow offers

A question, pin or follow may name another live match of the demo; it is read at that match's own position and the result carries `other_match` (teams, crests, never its score). A story answer may carry a "Follow this story?" offer (Decision-1 yes/no, thresholds in the `follow-offer` config); stat answers never do. No match's own narratives mention another.

### 8d. Replay playback (sting and slow motion)

Every replay and clip playlist carries `playback`: a hold, the `builtin:league` sting, a cut and fades between clips, and slow motion into and out of marked events (`replay-timing` config: `min_clip_seconds` 8 s, lead-ins per event kind). Clips reference published HLS segments only; the viewer plays them on a second stage player while live continues in a corner.

## Decisions and limits

| We chose | Because |
| --- | --- |
| Microsoft emulators, not LocalStack | Account-free; same SDKs and names as Azure |
| The feed on its own Postgres and network | Our services see it only through Event Hubs and HLS over HTTP |
| Demo control outside the product services | No product service learns about the others; a release drops it |
| Seeds recorded on the pipeline, restored through demo-only adapters | Nothing past a start point can exist; core services never branch on a demo |
| Skip ahead moves run clocks rather than chaining seeds | No new matchIds; follows and sessions carry on |
| SQL Server 2022 in the shared stack (ETL's own compose: 2025) | The one `sql` container also stores the Service Bus emulator's state |

Troubleshooting: emulators keep no messages across a restart (the services reconnect; after an Event Hubs restart run `./dev demo start` again); a Service Bus emulator "throttled" (50002) under host load → `docker restart itg-local-servicebus-1`; a Cosmos emulator stuck after a hard host restart → remove its stale `postmaster.pid` and restart it; questions and narratives share the local model (`NARRATIVE_MODEL_CONCURRENCY` 2, `QUESTION_TIMEOUT_SECONDS` 240), so three matches put narratives minutes behind.
