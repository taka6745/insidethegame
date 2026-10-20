# Chelsea–United simulator demo

```text
GRF native contacts + frames → vendor adapter → timed recording → ETL
                      └────→ video + score strip ─────────────→ player
```

**Local generator implemented.** Real-name illustrative lineups map the simulator's slots; abilities remain generic. This is a synthetic game, not actual Premier League footage or official Opta data.

## Run

Requires the existing instrumented native GRF runtime, NumPy, OpenCV and FFmpeg. The capture/encoder currently targets macOS (VideoToolbox). The optional presentation source clone lives under ignored `.local/`; production services do not import GRF.

```sh
# Existing local runtime; output folder must not exist.
GRF_SOURCE="$PWD/.local/grf-demo-source" data-generation/generate-grf.sh
python3 -m unittest discover -s data-generation/tests -v
```

`GRF_PYTHON` selects a different installed instrumented Python runtime. `GRF_SEED` selects a seed. The native telemetry/render instrumentation is preserved as reference in `legacy/data/GoogleResearchFootball/{telemetry,render}.patch`; no archived scripts run. GRF upstream is pinned at `3d9e754720a95621bba6475c4d3b0d56fe919014`.

For telemetry v2, realism and cosmetic customization, copy the installed instrumented source to a disposable directory, excluding prior build output. Run `python -m grf_demo.prepare_cosmetics <copy>`, `python -m grf_demo.prepare_telemetry <copy>` and `python -m grf_demo.prepare_realism <copy>`, rebuild its engine with CMake, and point `GRF_SOURCE` at that copy. Each patch validates its pinned-source anchors. The patch changes names/team labels and blue/red kit textures; it does not assign real player abilities. Never patch `legacy/` or the original installed runtime. Keep upstream licences with the source copy.

The presentation patch removes the minimap, adds each roster slot's illustrative shirt number directly to its native back-of-shirt texture, and uses a higher, wider ball-follow camera. Numbers move with the player mesh; they are not screen labels. `SHIRT_NUMBERS` in `grf_demo/roster.py` owns the mapping. Already customised disposable sources can run `python -m grf_demo.prepare_presentation <copy>` repeatedly before rebuilding. Camera zoom/height replacements live in that module (0.7/0.5; original 0.5/0.3). The viewer preserves the complete 16:9 frame with `object-fit: contain`; wider containers may have side margins. Existing videos are unchanged until recaptured.

## Timing and meaning

- Equal built-in AI difficulty with the [realism patch](opta-events.md#realism-patch). Two 45-minute halves of active play are captured in **real time**: `videoSeconds` equals capture seconds.
- The broadcast clock follows the video and runs through dead play, so each half ends in stoppage time. The packaged score strip draws the same clock. The video-frame/native-clock mapping stays in ignored `frames.jsonl.gz`.
- Events follow the [Opta-style contract](opta-events.md) and are timestamped at resolution. Continuous same-player/function/type contact callbacks (gaps ≤ 300 ms) form one action.
- A successful attempt is represented once, as `goal`. A goal's team follows the score change; the scorer stays unknown when the last touch belongs to the other team.
- `touch` records every executed contact, including those within passes and attempts. Never add touches to other action counts.
- `possession_samples` contains seconds of **confirmed native ownership**, excluding loose balls and restarts. ETL calculates percentages; the backend never does.
- Fouls are **whistled native fouls**. Offsides and cards come from referee decisions. `body_part_event_types` certifies complete categories in this **immutable recording** only.
- xG, VAR, injuries, substitutions and own-goal attribution remain unavailable. Rare events have explicit test fixtures; none are invented in the viewer's match.

`package.py` writes the strip video (keyframe every 2 s), two-second HLS segments, `recording.json` and `recording.opta-f24.json`.

`raw.jsonl.gz`, source video, styled video and final `match.mp4` remain ignored. The small delivery recording may be committed. Runtime rendering can change the simulation trajectory: the recording produced from the **rendered capture** is authoritative, never a separate headless seed run.

GRF source: [Google Research Football](https://github.com/google-research/football), Apache-2.0; Gameplay Football engine, Unlicense. Rendered upstream assets retain their original provenance; the simulator's asset rights are not a licence to real broadcast footage or official team branding.
