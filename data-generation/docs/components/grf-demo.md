# GRF demo generator (`grf_demo/`)

> **In short:** renders a 90-minute Google Research Football match in real time, turns its native contacts into Opta-style events and packages aligned video. Offline developer tooling: the feed only imports its exporters (`opta.py`, `opta_stream.py`, `roster.py`).

| | |
| --- | --- |
| **Status** | Implemented and tested; three rendered, tactically scripted recordings shipped |
| **Needs** | The instrumented native GRF runtime, NumPy, OpenCV, FFmpeg; capture targets macOS (VideoToolbox) |
| **Writes** | `.local/grf-demo-<fixture>-90/` (ignored): `recording.json`, `recording.opta-f24.json`, `hls/`, raw telemetry |
| **Shipped** | [recordings](recordings.md) |
| **Source** | [Google Research Football](https://github.com/google-research/football), Apache-2.0 (pinned `3d9e754720a95621bba6475c4d3b0d56fe919014`) |

```text
GRF native contacts + frames → vendor adapter → timed recording → feed
                      └────→ video + score strip → HLS ─────────┘
```

Fictional Elephant League lineups (`grf_demo/league.json`) map the simulator's slots; abilities remain generic. This is a synthetic game, not real football footage or official Opta data.

## 1. Run

*In short: one disposable engine copy per fixture, then capture, translate, package.*

```sh
data-generation/prepare-grf-source.sh redcastle-portalbion   # → .local/grf-demo-source-redcastle-portalbion
GRF_FIXTURE=redcastle-portalbion GRF_SEED=31 GRF_SOURCE="$PWD/.local/grf-demo-source-redcastle-portalbion" \
  data-generation/generate-grf.sh .local/grf-demo-redcastle-portalbion-90
```

Then ship it: copy `recording.json` to `recordings/<fixture>-grf.json` and `recording.opta-f24.json` to `recordings/<fixture>-grf.opta-f24.json`, and run `python -m grf_demo.opta_stream recordings/<fixture>-grf.json` from `data-generation/`. The feed picks up the recording on its next start and the HLS from `.local/media/<fixture>/hls/` (`./dev` links a packaged `.local/grf-demo-<fixture>-90/hls/` there).

`GRF_PYTHON` selects a different installed instrumented Python runtime; `GRF_SEED` the seed (default 37). The native telemetry/render instrumentation is preserved as reference in `legacy/data/GoogleResearchFootball/{telemetry,render}.patch`; no archived scripts run.

## 2. Fixtures

*In short: `FIXTURES` in `roster.py` is the generator's fixture list.*

`FIXTURES` builds each match from `league.json`'s fictional lineups, shirt numbers, kit colours, score-strip colours and codes: `riverton-forgeham` (default), `redcastle-portalbion` and `skybridge-whitmore`. Names are compiled into the engine, so each fixture needs its own disposable source. Exports (and the feed's MA1 branding) read the fixture from the recording's team ids.

## 3. Source patches

*In short: patch a disposable copy, never `legacy/` or the installed runtime.*

`prepare-grf-source.sh` copies the installed instrumented source without build output, runs `python -m grf_demo.prepare_cosmetics`, `prepare_telemetry`, `prepare_realism` and `prepare_tactics` on it and rebuilds the engine with CMake. Each patch validates its pinned-source anchors. The cosmetics patch changes names, team labels and kit textures; it does not assign real player abilities. Keep upstream licences with the source copy.

The presentation patch (`python -m grf_demo.prepare_presentation <copy>`, repeatable before rebuilding) removes the minimap, adds each slot's illustrative shirt number to its native back-of-shirt texture (`SHIRT_NUMBERS` in `roster.py`), and uses a higher, wider ball-follow camera (zoom/height 0.7/0.5; original 0.5/0.3). Existing videos are unchanged until recaptured.

## 4. Scripted tactics

*In short: per-fixture scripts steer the built-in AIs through five engine knobs, so multi-minute patterns are real.*

Unscripted GRF minutes behave like independent draws: no spells, momentum or game-state behaviour. `prepare_tactics.py` adds per-team runtime knobs to the engine (`set_tactic(team, knob, value)`); the defaults keep upstream behaviour. The built-in AIs still make every decision; the knobs bias them:

| Knob | Range (default) | Engine effect |
| --- | --- | --- |
| `press` | 0–1 (0.5) | How far, and with how many players (3 above 0.75), the team hunts the ball carrier; a low value lets a deep opponent keep the ball |
| `line` | −0.5–0.5 (0) | Moves the block up or down and adds to the native offensiveness (line height, support runs) |
| `flank` | −1–1 (0) | In possession, shifts shape and pass choice to the right (+) or left (−) wing |
| `direct` | 0–1 (0) | Pass choice favours forward progress |
| `energy` | 0–1 (1) | Off-ball running speed and pressing range (fatigue) |

[`tactics.json`](../../grf_demo/tactics.json) holds each fixture's script: a style per team and phases in broadcast minutes. A phase steers its team (`set`) and optionally the opponent (`opponent`), can ramp, and can apply only when its team is `leading`, `trailing` or `level`. [`tactics.py`](../../grf_demo/tactics.py) evaluates the script once per video second and sets changed knobs. The script and every change (time, score, active phases, values) are in `provenance.tactics`; `capture.py --no-tactics` renders the built-in AIs alone.

Existing source copies take the patch with `python -m grf_demo.prepare_tactics <copy>` and `make` in `third_party/gfootball_engine`.

## 5. Timing and meaning

*In short: real-time capture; the recording from the rendered run is authoritative.*

- Equal built-in AI difficulty with the [realism patch](../../contracts/README.md#realism-patch) and [scripted tactics](#4-scripted-tactics). Two 45-minute halves of active play are captured in **real time**: `videoSeconds` equals capture seconds.
- The broadcast clock follows the video and runs through dead play, so each half ends in stoppage time. The packaged score strip draws the same clock. The video-frame/native-clock mapping stays in ignored `frames.jsonl.gz`.
- Events follow the [Opta-style contract](../../contracts/README.md) and are timestamped at resolution. Continuous same-player/function/type contact callbacks (gaps ≤ 300 ms) form one action.
- A successful attempt is represented once, as `goal`. A goal's team follows the score change. Without an attempt by the scoring team, the other team's last touch is that player's own goal (`ownGoal`); a deflected attempt keeps an unknown scorer.
- `touch` records every executed contact, including those within passes and attempts. Never add touches to other action counts.
- `possession_samples` contains seconds of **confirmed native ownership**, excluding loose balls and restarts. ETL calculates percentages; the backend never does.
- Fouls are **whistled native fouls**. Offsides and cards come from referee decisions. `body_part_event_types` certifies complete categories in this **immutable recording** only.
- xG, VAR, injuries and substitutions remain unavailable.

`package.py` writes the strip video (keyframe every 2 s), two-second HLS segments, `recording.json` and `recording.opta-f24.json`. Raw telemetry, source video and `match.mp4` stay ignored. Runtime rendering can change the simulation trajectory, so a separate headless run of the same seed is never a substitute.

## 6. Licences

*In short: GRF is Apache-2.0; nothing grants rights to real footage or branding.*

Gameplay Football engine: Unlicense. Rendered upstream assets retain their original provenance; the simulator's asset rights are not a licence to real broadcast footage or official team branding.
