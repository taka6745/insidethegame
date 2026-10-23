# Demo control

> **In short:** the demo's operator between the simulated provider and our services: Start demo, Skip ahead, Cancel demo, start progress, and the seeds behind mid-match starts. Not a product service; no product service learns about the others through it.

| | |
| --- | --- |
| **Code** | [`demo_control.py`](../../demo_control.py) (CLI and `serve`), [`test_demo_control.py`](../../test_demo_control.py) |
| **Runs** | Compose `demo-control` (backend image, script mounted); Azure `demo-control` Container App ([deployment](../deployment.md)) |
| **Public API** | `/demo-api/{start,cancel,skip,state,status}` through nginx, no login ([contract §7a](../../contracts/README.md#7a-demo-control-public)) |
| **Owners** | `OWNERS`: feed, ETL, engine, backend (base URL + optional admin token); purge order feed first |

```text
viewer ─ /demo-api/{start,cancel,skip,state,status} ─▶ demo-control ─┬▶ feed  /demo/start · /demo/skip · /runs/{id}/release
                                                                     ├▶ ETL, engine, backend  /admin/matches/{purge,export,restore}
                                                                     └▶ /seeds/{seed_id}/manifest.json + {owner}/{fixture}.json
```

## 1. Actions

*In short: every action is idempotent; the feed caps concurrent runs, so repeated clicks start one demo.*

| Action | What happens |
| --- | --- |
| Start (kickoff) | Purge the previous demo's finished matches, then the feed starts the three fixtures, main game first, staggered |
| Start (20′, HT, 60′, 85′) | The feed creates waiting runs; each owner restores the seed under the new ids (ETL alongside the backend, then the engine); runs are released main game first; any failure purges them (`503`), a stale seed is `409` |
| Skip ahead | Forwards to the feed's `/demo/skip`: every run's clock moves on by the same minutes, matchIds stay, so follows and sessions carry on |
| Cancel | Purge every match from every owner, feed first, then the others at once |
| State | Start points (`ready` only when kickoff or a fitting seed), live runs, `live_from`, the main game, recording runs, skip targets, `pending` and `last` |
| Status | Seven stages from real checks (feed, Event Hubs, ETL, Service Bus, engine, backend, viewer); also wakes apps scaled to zero |

Start and cancel answer `202` at once and run one after another under one lock (one replica); the viewer polls `/state`. Start, cancel and skip share one rate limit (10/min, burst 5); state and status are limited per client (40/s, burst 200).

## 2. Seeds

*In short: a seed is recorded on the pipeline, never reconstructed, so nothing past its point exists.*

```sh
docker compose -p itg-local exec demo-control python /checks/demo_control.py record 20             # held runs from kickoff
docker compose -p itg-local exec demo-control python /checks/demo_control.py capture 20            # wait until settled, save
docker compose -p itg-local exec demo-control python /checks/demo_control.py record ht --from 20   # chain HT, 60, 85
docker compose -p itg-local exec demo-control python /checks/demo_control.py adopt 20-20261022T184253Z   # a seed copied from another stack
```

- `record {point}` starts one *held* run per demo fixture: the feed sends nothing at or past the point, HLS included. `capture {point}` waits until every owner settled on what was sent (ETL watermark at the run's seq, the engine has summarised the last minute with nothing queued, the backend holds every event and engine narrative), exports each owner's rows, names the seed on the feed's start point and purges the runs.
- Layout: `manifest.json` (format 2, seed id, point, each owner's schema fingerprint, per fixture the source match and run ids, seq and video second) and `{owner}/{fixture}.json`. Locally `.local/seeds/`; on Azure an Azure Files share; both mounted at `/seeds`.
- Restore rewrites each fixture's seed to the new matchId and runId (its MA1 time to now) and is bounded by the seed's seq. Each owner refuses (`409`) another schema, a known or tombstoned match, rows of another match and rows past the seq; a seed whose seq differs from where the feed resumes is refused too.
- Seeds offered at the picker are read into memory on the first `/state`, so a seeded start does not wait on the share.
- `adopt` offers a seed copied from another stack at its own start point. The ETL fingerprint leaves out the stand-in's `localStreamWindows`, so Azure and local seeds fit both.
- Recording runs are no demo: `state` lists them as `recording`, the viewer never opens them, and Start is `409` while one runs. Don't record during a demo.

| Owner | Restores | Not seeded |
| --- | --- | --- |
| feed | Run resumes at the point (`resume_point`), no MA1 | — |
| ETL | Every match table (events, SPADL, trend inputs, progress, windows); the worker reloads from SQL | — |
| engine | Checkpoint, context blocks, narratives, analyses, storylines | Viewers' follow decisions and narratives |
| backend | Received match and events, gaps, audience catalogue, engine narratives and their key-event clips | Sessions, follows, questions, calculations |

Seed routes exist only with `DEMO_SEEDS=1`, in one demo adapter per owner; without it there is no export or restore route and the feed refuses seed recording (`403`) and seeded starts (`409`). Restore writes rows as the live pipeline does, then the owner adopts the match as after a restart; core services never branch on a demo.

## 3. Between demos

*In short: keep the pipeline warm while a demo is live; tidy up after.*

| Loop | Behaviour | Setting |
| --- | --- | --- |
| Keep warm | While a demo is live, every owner's `/health` and each extra URL is pinged so no app scales to zero mid-match (Container Apps cool down after 300 s); a viewer at the picker also wakes them, at most once a round | `DEMO_KEEP_WARM_SECONDS` (60), `DEMO_KEEP_WARM_URLS` |
| Sweep | Once no demo or recording is live and a run has been finished long enough, its matches are purged from ETL, engine and backend, outside the start/cancel lock; Start purges any leftovers itself, in parallel, before releasing the new runs | `DEMO_SWEEP_GRACE_SECONDS` (900) |
| Stream start | Azure only: Start calls the spend guard's stream-start webhook on its own thread, so Stream Analytics need not wait for the traffic alert (a secret URL, never logged) | `DEMO_STREAM_START_URL` |

Other settings (defaults in seconds unless noted):

| Setting | Default |
| --- | --- |
| `DEMO_FEED_URL`, `ETL_ADMIN_URL`, `ENGINE_ADMIN_URL`, `BACKEND_URL` | Compose service URLs; `ETL_ADMIN_TOKEN`, `ENGINE_ADMIN_TOKEN` on Azure |
| `DEMO_PURGE_TIMEOUT`, `DEMO_PURGE_RETRIES`, `DEMO_PURGE_RETRY_SECONDS` | 300, 10 tries, 2 |
| `DEMO_STATUS_CACHE_SECONDS` | 1 |
| `DEMO_RELEASE_LEAD` | 5 (last restore to the first run reading the point) |
| `DEMO_CAPTURE_POLL`, `DEMO_CAPTURE_TIMEOUT` | 5, 1800 |
| `DEMO_SEED_ROOT` | `/seeds` |

## 4. Tests

*In short: a fake feed and owners behind `httpx.MockTransport`.*

```sh
cd local && python3 -m pytest -q test_demo_control.py
```

Covers one demo under concurrent clicks, purge order, seeded restore order and id rewrite, staggered release, purge on a failed restore, the settle check, keep-warm, the sweep and the stream-start thread. CI runs it.
