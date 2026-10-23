# Development

> **In short:** the feed runs in the shared Docker stack; its tests need only Python (plus a throwaway Postgres for the repository tests). The generator needs the native GRF runtime and is run only to make a new recording.

| | |
| --- | --- |
| **Needs** | Python 3.12; Docker for the stack; GRF runtime, OpenCV and FFmpeg only to render |
| **Tests** | `python -m pytest -q` from `data-generation/`. Repository and Blob tests skip without `FEED_TEST_DATABASE_URL` and `FEED_TEST_BLOB_CONNECTION_STRING` (Azurite). OpenCV and GRF-clone tests skip without those installed |
| **Whole product** | `ACCEPT_EULA=Y ./dev up backend`, then `./dev demo start` ([../../DEVELOPMENT.md](../../DEVELOPMENT.md)) |
| **Logs** | `./dev logs feed` |

## 1. Run the feed

*In short: the stack starts it; `./dev demo start` purges and starts runs.*

`./dev demo start [fixture…]` purges every owner, then calls `POST /runs` for each fixture with `kickoff: "next-minute"`. The admin API is on `http://localhost:18030` (`/docs`) and, for `/dev/`, behind nginx at `/feed-api/`. The demo is started from the viewer's **Start demo** (demo control → `POST /demo/start`); seeds are recorded with `local/demo_control.py record|capture {point}` ([feed §2a](components/feed.md#2a-demo-and-seeds)). `./dev` mounts each `.local/grf-demo-<fixture>-90/hls/` that exists ([feed §5](components/feed.md#5-recordings-and-media)).

## 2. Tests

*In short: virtual clock for the feed; real recordings for everything else.*

```sh
cd data-generation
pip install -r feed/requirements-test.txt
python -m pytest -q                                                      # everything
FEED_TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/feed_test python -m pytest -q feed   # + Postgres
```

| Suite | Proves |
| --- | --- |
| `feed/tests/test_feed.py` | MA1 lead, send order and `seq`, nothing ahead of the clock, two concurrent runs, restart resume, HLS gate and 404s, purge (incl. an in-flight segment copy) and tombstones, seek off by default; Start demo (one demo under concurrent calls, main game first, run cap 409), held runs stop at their point, seeded runs wait for release then resume without MA1, no seed path without `DEMO_SEEDS` |
| `feed/tests/test_feed_db.py` | Migrations, runs, catalogue sync, tombstones and cut-off on real Postgres |
| `feed/tests/test_blob.py` | Blob Storage HLS gate and purge (Azurite or a throwaway account) |
| `tests/test_opta_stream.py`, `test_fixture_recordings.py` | Exports reproducible from the recordings; scores, goals, cards and ETL reference totals pinned for `redcastle-portalbion` and `skybridge-whitmore` (`riverton-forgeham` in `test_recording.py`) |
| `tests/test_opta_events.py`, `test_telemetry_v2.py`, `test_grf_demo.py` | Event derivation rules; the feed's event types and qualifiers equal the backend `Event` contract |
| `tests/test_fixtures.py` | Rosters, kits, exports follow the recording |
| `tests/test_tactics.py` | Tactic phases, the shipped scripts, and the engine patch on the pinned source |
| `tests/test_presentation.py`, `test_realism_patch.py`, `test_recording.py` | Roster numbers and kit textures repeatable; realism patch idempotent on the pinned engine; shipped recording integrity |

## 3. Make a recording

*In short: see the generator page.*

[components/grf-demo.md](components/grf-demo.md): prepare a source copy, render, then ship the recording and regenerate its exports.
