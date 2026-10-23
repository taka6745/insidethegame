# Feed (`feed/`)

> **In short:** the simulated external match-data and broadcast provider. It replays recorded fixtures as live matches, several at once, and our services see only its Event Hubs stream and its HLS over HTTP. Nothing is sent, and no segment is served, before the run's clock reaches it.

| | |
| --- | --- |
| **Status** | Implemented and tested (virtual-clock unit tests; Postgres repository tests); runs in the local stack as Compose service `feed` (profile `backend`); Start demo, main game and seeded runs tested in units and on the local stack |
| **Owns** | Its own Postgres server (locally `feed-postgres`, on a network only the feed joins), database `feed`: recordings catalogue, runs, purge tombstones, `demo_settings` ([migrations](../../feed/migrations/) 001–008) |
| **Out** | Event Hubs `match-events`, partition key `matchId`: MA1, `MatchEvent` v2, MA3, POS ([local contracts](../../../local/contracts/README.md#2-matchevent-v2), [ETL contracts](../../../etl/contracts/README.md)) |
| **Media** | `GET /hls/{matchId}/live.m3u8` and its segments: played footage only ([§6](../../../local/contracts/README.md#6-live-media-hls)) |
| **Admin (dev only)** | `GET /recordings`, `POST /runs`, `GET /runs`, `POST /admin/matches/purge`, `GET`/`PUT /demo`, `POST /demo/start`, `GET /health`; with `DEMO_SEEDS=1` also `POST /runs/{matchId}/release` and `POST /demo/skip` ([§7](../../../local/contracts/README.md#7-feed-admin-api-dev-only)). Public `/demo-api/` goes through demo control, never straight here |
| **Host port** | `ITG_FEED_PORT` (default 18030) |

## 1. Layout

*In short: the usual layers, one file each.*

| File | Role |
| --- | --- |
| `app.py` | Composition root (`uvicorn feed.app:from_env --factory`) |
| `models/stream.py` | `FixtureStream`: one fixture's items in send order, independent of any run |
| `adapters/recordings.py` | Discovers `recordings/*.json`, builds each stream (MA1/MA3/POS from `grf_demo.opta_stream`, `MatchEvent` v2 bodies) |
| `adapters/eventhubs.py` | Event Hubs producer, one partition key per match |
| `adapters/hls.py` | Live playlist: copies a packaged segment in only once it has played (disk directories) |
| `adapters/blob.py` | The same directories in Azure Blob Storage |
| `services/feed.py` | Catalogue, runs (capped by `demo_settings.max_active_runs`), the demo start, purge |
| `services/run.py` | One run on the wall clock |
| `services/clock.py` | Wall clock; tests substitute a fake |
| `services/render.py` | Stamps a run's `matchId`, `runId` and wall-clock times onto the stream |
| `repositories/feed_db.py` | The `feed` database |
| `routes/http.py` | Admin API and HLS origin |

## 2. A run

*In short: `matchId = {fixture}-{run8}`, from 00:00, at video pace.*

```text
recordings/*.json ─┐                    ┌─▶ MA1 (kickoff − 60 s)
media/{fixture}/hls ┼─▶ run (wall clock) ┼─▶ per event: MatchEvent v2 → its MA3 rows; POS by video time
feed DB (runs) ────┘                    └─▶ live-media/{matchId}/ → /hls/{matchId}/live.m3u8
```

- `POST /runs` mints `matchId = {fixture}-{first 8 hex of runId}`; matchIds are never reused. `kickoff: "next-minute"` is the first whole UTC minute at least 60 s ahead, so MA1 leads by about a minute.
- Each item is sent only when the run's video clock reaches it (POS before events at the same time), with its timestamp rebased to wall time. MA3 timestamps keep the ETL window rule (each period starts 0.5 s after a minute boundary), so second-half MA3 rows can be stamped up to a minute after they are sent.
- Progress (`position`, `seq`, `status`) is saved after each send. After a restart, unfinished runs resume from it and send whatever has become due; delivery is at least once.
- `FEED_ALLOW_SEEK=1` (dev only, off by default) allows `start_seconds` on `POST /runs`.

## 2a. Demo and seeds

*In short: one demo of exactly the configured fixtures; seeded starts wait for every owner's restore, then play on.*

| Piece | Behaviour | Status |
| --- | --- | --- |
| `demo_settings` (002, 005) | Fixtures, `main_fixture` (default `redcastle-portalbion`), `stagger_seconds` 120, `max_active_runs` 3, start points (kick-off, 20′, second half, 60′, 85′; each maps to every fixture's own video second, `seed` names the recorded seed); `GET`/`PUT /demo` edit it from `/dev/`, revision-checked | Unit + Postgres tests |
| `POST /demo/start {point}` | Once: while any run is scheduled or live it returns those runs (concurrent clicks make one demo). Purges finished runs, then creates the fixtures main game first, staggered. A failure part-way purges what it made | Unit tests; local stack |
| `POST /demo/skip {target}` | Demo fast-forward (`DEMO_SEEDS=1`): moves every playing demo run's kickoff back by the same whole minutes (`skip_targets` in the demo settings, migration 007), restarts its task at the saved position (keeping any send back-off); without `DEMO_SEEDS` `GET /demo` lists no targets. What became due goes out at once in capped sends, video publishes to the new clock. Whole minutes keep the ETL's minute windows aligned; nothing past the new clock is sent | Unit tests (virtual clock); Postgres repository test |
| Cap | `POST /runs` past `max_active_runs` is `409`, so `/dev/` starts obey it too | Unit tests |
| Held run (003, 006) | `POST /runs {hold_point}` sends nothing at or past the point's video second (HLS included): demo control records a seed from it; the run lists the point as `held_at`, which capture checks | Unit tests; four seeds recorded locally |
| Waiting run (003, 004) | A seeded start (or `resume_point`) creates the run waiting (`awaiting_restore: true`): nothing sent; position and seq taken as delivered. `POST /runs/{id}/release {after_seconds}` starts its clock at the point, without MA1 or earlier events; idempotent. `start_point` is kept so the viewer says "live from N′" | Unit tests; local stack |

Seed recording and seeded starts exist only with `DEMO_SEEDS=1` (local compose and the demo build): without it `hold_point`/`resume_point` are `403`, a seeded start `409` and `release` is absent. A point with no recorded seed is `409`. The seed layout and restore order live in demo control (`local/demo_control.py`, [seeds](../../../local/docs/components/demo-control.md#2-seeds)).

## 3. HLS

*In short: the served directory never holds footage past the run's clock.*

A packaged segment is hard-linked (or copied) into `live-media/{matchId}/` once its end ≤ the run's video clock, then the `EVENT` playlist is rewritten atomically. The playlist is 404 until the first segment exists and after a purge; `#EXT-X-ENDLIST` follows the last segment. The route serves only plain file names inside a valid matchId directory.

## 4. Purge

*In short: tombstone first, then stop, then delete.*

`POST /admin/matches/purge` writes a permanent tombstone (and for `all` a cut-off), cancels the run, waits for any in-flight segment copy or progress write, deletes the run row and removes its HLS directory. Unknown ids still get a tombstone. Tombstoned or pre-cut-off runs never resume.

## 5. Recordings and media

*In short: any recording whose teams match a roster fixture; media is optional.*

Every `recordings/*.json` (not an `.opta-*` export) whose team ids match a [`roster.py`](../../grf_demo/roster.py) fixture (built from [`league.json`](../../grf_demo/league.json)) is loaded; events and possession samples must be in video order. Media is `FEED_MEDIA_ROOT/{fixture}/hls/match.m3u8` (one read-only mount of `ITG_MEDIA_ROOT` in `local/compose.yaml`); without it the run has `capabilities.video: false`. Only this container mounts recordings and media.

## 6. Settings

*In short: environment only.*

| Variable | Default | Meaning |
| --- | --- | --- |
| `FEED_DATABASE_URL` | required | Postgres; the database is created if missing |
| `FEED_EVENTHUB_CONNECTION_STRING` | required | Event Hubs namespace |
| `FEED_EVENTHUB_NAME` | `match-events` | Hub |
| `FEED_RECORDINGS_DIR` | `/recordings` | Recordings (read-only) |
| `FEED_MEDIA_ROOT` | unset | Packaged HLS per fixture (read-only) |
| `FEED_LIVE_DIR` | `/live-media` | Played segments (feed-internal volume) |
| `FEED_ALLOW_SEEK` | `0` | Dev only |
| `DEMO_SEEDS` | `0` | `1`: held and released runs, seeded demo starts (demo build; off for a production release) |
| `FEED_SEND_MAX_ITEMS` | `200` | Items per Event Hubs send (ingress is about 1,000 events/s per throughput unit) |
| `FEED_SEND_RETRY_FIRST_SECONDS` / `FEED_SEND_RETRY_MAX_SECONDS` | `2` / `60` | Back-off after a refused send, doubling while refusals get nothing through |
| `FEED_SEND_THROTTLE_WAIT_SECONDS` | `10` | Minimum wait after a `server-busy` refusal |
| `FEED_BLOB_CONNECTION_STRING` | unset | Azure: recordings, media and played HLS in Blob Storage instead of the three directories ([deployment](../deployment.md#2-azure)) |
