# Data generation

Renders synthetic fictional-league matches with Google Research Football and replays them through the **feed**, a simulated external provider, as live matches: several at once, into Event Hubs and HLS. The feed also starts the three-match demo, from kick-off or a seeded start point. Every message and recording is labelled `synthetic: true`; none is Stats Perform data or an actual match.

![Recordings and media go into the feed, which publishes to Event Hubs and serves played HLS](architecture.svg)

| Part | Role |
| --- | --- |
| `grf_demo/` | Offline: render a tactically scripted 90-minute match in real time, derive Opta-style events from native contacts and referee decisions, package aligned video as HLS |
| `recordings/` | Three shipped matches: `<fixture>-grf.json` (canonical), `.opta-f24.json` (F24-style), `.opta-stream.jsonl` (MA1/MA3 messages) |
| `feed/` | Live: one asyncio task per run sends MA1 a minute before kickoff, then `MatchEvent` v2, MA3 and POS at video pace, and publishes each HLS segment once it has played; its own Postgres `feed` (catalogue, runs, `demo_settings`, tombstones) |
| `contracts/` | `match-event.schema.json`-compatible Opta-style event contract ([below](#event-contract)) |
| `infra/` | Terraform for the feed on Azure, mock-tested |
| `docs/grf/` | `telemetry.patch` (read-only C++ telemetry hooks) and `render.patch` (real-time clock and render) applied to a disposable copy of the pinned GRF source |

Simulator: [Google Research Football](https://github.com/google-research/football/tree/3d9e754720a95621bba6475c4d3b0d56fe919014) (Google LLC, Apache-2.0; Gameplay Football engine, Unlicense), archived 19 August 2026. Its asset rights are not a licence to real footage or team branding; football realism is not statistically validated, which is why fixtures are scripted.

| Fixture | Score | Notes |
| --- | --- | --- |
| `riverton-forgeham` | 1–1 | Two penalties; Riverton press and attack right, Forgeham direct down the left and tire from 70′ |
| `redcastle-portalbion` (main game) | 1–0 | Goal in first-half stoppage; Port Albion press high and tire from 70′; full video quality on Azure |
| `skybridge-whitmore` | 1–1 | Own goal, equaliser, a second-yellow dismissal; Whitmore sit deep and counter |

## Run it

| Command | Does |
| --- | --- |
| `ACCEPT_EULA=Y ./dev up backend` then `./dev demo start [fixture…]` | The feed in the shared stack (`http://localhost:18030/docs`, `/feed-api/` behind `/dev/`); `./dev logs feed` |
| **Start demo** in the viewer | Demo control → `POST /demo/start {point}`: exactly the configured fixtures, main game first, staggered; a seeded point creates waiting runs that demo control restores and releases |
| `cd data-generation && pip install -r feed/requirements-test.txt && python -m pytest -q` | Everything; `FEED_TEST_DATABASE_URL=postgresql://…` adds the Postgres repository tests, `FEED_TEST_BLOB_CONNECTION_STRING` (Azurite) the Blob tests; OpenCV and GRF tests skip without those installed |
| `prepare-grf-source.sh <fixture>` then `GRF_FIXTURE=<fixture> GRF_SEED=31 GRF_SOURCE=.local/grf-demo-source-<fixture> generate-grf.sh .local/grf-demo-<fixture>-90` | Render a new recording (needs the native GRF runtime, NumPy, OpenCV, FFmpeg; macOS capture). Then copy `recording.json` and `recording.opta-f24.json` into `recordings/` and run `python -m grf_demo.opta_stream recordings/<fixture>-grf.json` |

| Test | Proves |
| --- | --- |
| `feed/tests/test_feed.py` | MA1 lead, send order and `seq`, nothing ahead of the clock, concurrent runs, restart resume, HLS gate, purge and tombstones, Start demo under concurrent calls, held and seeded runs, no seed path without `DEMO_SEEDS` |
| `feed/tests/test_feed_db.py`, `test_blob.py` | Migrations, runs, catalogue, tombstones on Postgres; Blob Storage HLS gate and purge |
| `tests/test_opta_*.py`, `test_telemetry_v2.py`, `test_fixture_recordings.py`, `test_recording.py` | Event derivation rules; exports reproducible; scores, goals, cards and ETL reference totals pinned per recording |
| `tests/test_tactics.py`, `test_realism_patch.py`, `test_presentation.py`, `test_fixtures.py` | Tactic scripts and engine patches on the pinned source; rosters and kits follow the recording |

## How the feed works

| Rule | Detail |
| --- | --- |
| Run | `POST /runs` mints `matchId = {fixture}-{first 8 hex of runId}`, never reused; `kickoff: "next-minute"`; MA1 at kickoff − 60 s; each item sent when the run's video clock reaches it, timestamps rebased to wall time; progress saved after each send, so a restart resumes |
| Sends | At most 200 items per send; a refused send backs off (2 s doubling to 60 s, at least 10 s on `server-busy`); nothing dropped, delivery at least once, consumers drop redeliveries by seq, MA3 id and sampleId |
| HLS | A packaged segment is symlinked into `live-media/{matchId}/` only once its end ≤ the run's clock, then the playlist is rewritten atomically; `404` before the first segment and after a purge; no seek on the demo path |
| Purge | Tombstone first (permanent; `all` also sets a cut-off), stop the task, delete the row and the HLS directory |
| Demo (`demo_settings`) | Fixtures, `main_fixture`, `stagger_seconds` 120, `max_active_runs` 3 (`409` past it), start points mapped to each fixture's video second; `POST /demo/start` returns the live demo while one runs, so concurrent clicks make one demo |
| Seeds (`DEMO_SEEDS=1`) | A *held* run sends nothing at or past its point (HLS included) so demo control can record a seed; a *waiting* run is created at a seeded start and released (`POST /runs/{id}/release`) once every owner holds the seed, without MA1; `POST /demo/skip` moves every playing run's clock back by whole minutes |
| Media | `FEED_MEDIA_ROOT/{fixture}/hls/match.m3u8` (one read-only mount; only this container mounts recordings and media); without it `capabilities.video: false` |
| Settings | `FEED_DATABASE_URL`, `FEED_EVENTHUB_CONNECTION_STRING`, `FEED_EVENTHUB_NAME` (`match-events`), `FEED_RECORDINGS_DIR`, `FEED_MEDIA_ROOT`, `FEED_LIVE_DIR`, `FEED_SEND_*`, `DEMO_SEEDS`, `FEED_BLOB_CONNECTION_STRING` (Azure), `FEED_ALLOW_SEEK` (dev only) |

Layers in `feed/`: `models/stream.py` (one fixture's items in send order), `adapters/` (recordings, Event Hubs, HLS directories, Blob Storage), `services/` (catalogue and runs, one run on the wall clock, render), `repositories/feed_db.py`, `routes/http.py` (admin API and HLS origin).

## Event contract

The canonical events in every recording (v3): Opta-style types and qualifiers derived from GRF's native contacts, referee decisions and 100 Hz tracking by the rules in `grf_demo/telemetry.py`; F24 ids in `grf_demo/opta.py`. Events are timestamped when they **resolve**, so live delivery never reveals the future. The broadcast clock runs through dead play (second half starts at 45:00; first-half stoppage keeps `periodId` 1 with `timeMin` ≥ 45); order by `sequence` or `(periodId, timeMin, timeSec)`. `x`, `y` are Opta 0–100 for the acting team (attack towards `x=100`); `possessionId` changes on every turnover and taken restart.

| Type | Rule | F24 |
| --- | --- | --- |
| `pass`, `clearance` | Intentional pass, success = next intentional contact by a teammate; target-less long ball from the defensive quarter under pressure | 1/2, 12 |
| `shot`, `goal`, `save` | Attempt with outcome `off_target`/`post`/`saved`/`blocked`; a score change is a `goal` (never also a shot; last touch by the conceding team = `ownGoal`); keeper or block save | 13–15, 16 (Q28), 10 |
| `interception`, `blocked_pass`, `tackle`, `dispossessed`, `take_on`, `challenge`, `aerial`, `ball_recovery` | Rules over tracking: pass speed and distance, contact timing, settled ownership, headers under contest | 8, 74, 7, 50, 3, 45, 44, 49 |
| `out`, `corner_awarded`, `keeper_claim`, `keeper_pickup`, `punch`, `offside`, `error`, `ball_touch` | Line crossings, keeper retention, referee decisions, turnovers followed by an attempt | 5, 6, 11, 52, 41, 55, 51, 61 |
| `foul`, `foul_won`, `card`, restarts (`corner`, `free_kick`, `throw_in`, `goal_kick`, `kick_off`, `penalty`) | Whistled native decisions; taken restarts | 4, 17, Q6/Q5/Q107/Q124/Q279/Q9 |
| `touch`, `period_start`, `period_end` | Every executed contact; phase transitions | –, 32, 30 |

Not available: substitutions, injuries, VAR, xG. Simulated football turns the ball over far more than real football (several hundred recoveries, about 1,400 passes at 75–78 %), with a third of the throw-ins and corners; the adapter reports what happened rather than rescaling. The realism patch (`prepare_realism.py`) and scripted tactics (`tactics.json`: `press`, `line`, `flank`, `direct`, `energy`, `form` knobs per team and phase, evaluated once per video second) keep goals near real levels and make multi-minute patterns real; every knob change is recorded in `provenance`.

## Deployment

The feed simulates a third party, so on Azure it gets its own resource group `rg-itg-feed-dev` (internal Container App, PostgreSQL Flexible B1ms, a Storage account) and only a send-only key for our Event Hubs; it shares just the ETL's Container Apps environment and registry. Applied by `./dev azure up` ([terraform](../terraform/README.md)); `demo_seeds` sets `DEMO_SEEDS` (`--release` leaves it off). Blob containers replace the volumes: `recordings` (downloaded at start), `media` (uploaded by `up`; the main game at full quality, the others at about 1.75 Mbit/s) and `live` (segments copied server-side only once played); `GET /hls/{matchId}/…` streams from `live`, so the frontend and backend see the same origin as locally. Recordings and media are never baked into the image.

## Decisions

| We chose | Because |
| --- | --- |
| Real-time rendered matches with aligned video, not a replay of an existing match | Events and footage must agree to the second |
| A feed service with its own database and container | Behaves like an external provider; nothing else mounts recordings or media |
| N runs at once, `matchId = {fixture}-{run8}`, permanent tombstones | Concurrent demos; every run isolated and purgeable; purged matches never come back |
| Opta-style events, F24 and MA1/MA3/POS exports | A widely known format for ETL |
| Played-only HLS, no seek | Future data is physically unreachable |
| Seeded starts from held runs, waiting runs released after restore | Mid-match starts with a real story so far, never reconstructed |
| Scripted per-fixture tactics | Unscripted GRF minutes behave as independent draws: no spells or game state for storylines |

Open: a new fixture needs entries in `grf_demo/league.json` and `roster.py` as well as a recording; seeds are recorded per build, so a schema change on any owner means recording them again.
