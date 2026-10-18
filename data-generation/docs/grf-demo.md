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

For telemetry v2 and cosmetic customization, copy the installed instrumented source to a disposable directory, excluding prior build output. Run `python -m grf_demo.prepare_cosmetics <copy>` and `python -m grf_demo.prepare_telemetry <copy>`, rebuild its engine with CMake, and point `GRF_SOURCE` at that copy. Both patches validate their pinned-source anchors. The patch changes names/team labels and blue/red kit textures; it does not assign real player abilities. Never patch `legacy/` or the original installed runtime. Keep upstream licences with the source copy.

The presentation patch removes the minimap, adds each roster slot's illustrative shirt number directly to its native back-of-shirt texture, and uses a higher, wider ball-follow camera. Numbers move with the player mesh; they are not screen labels. `SHIRT_NUMBERS` in `grf_demo/roster.py` owns the mapping. Already customised disposable sources can run `python -m grf_demo.prepare_presentation <copy>` repeatedly before rebuilding. Camera zoom/height replacements live in that module (0.7/0.5; original 0.5/0.3). The viewer preserves the complete 16:9 frame with `object-fit: contain`; wider containers may have side margins. Existing videos are unchanged until recaptured.

## Timing and meaning

- Equal built-in AI difficulty. Native active play is two six-minute halves; the displayed football clock scales to 90 minutes.
- Native dead play makes capture longer than 12 minutes. Packaging scales **each half** independently to 360 video seconds, and applies exactly the same mapping to events and possession samples.
- `videoSeconds` schedules delivery; `timeMin/timeSec` remains the football clock. The original video-frame/native-clock mapping stays in ignored `frames.jsonl.gz`.
- Continuous same-player/function/type contact callbacks (gaps≤300ms) form one action. This removes repeated physics callbacks during one animation.
- Pass completion is the next intentional teammate contact; failures include opponent contact/self-recovery/stoppage. Unresolved export-end passes have unknown outcome.
- A successful shot is represented once as `goal`, matching the application's existing event contract. Its native shot contact remains in raw capture. Nonintentional deflections preserve shot association; a new intentional contact or stoppage ends it. A goal's team follows score change; scorer stays unknown when the last touch belongs to the other team.
- `touch` records include contacts accompanying passes and attempts, plus deflections. Count those records alone for captured contacts; adding the other action categories double-counts them.
- Unknown-scorer goals retain the team attempt but lose player-level shot attribution in the compact event contract. Named-player shot counts are attributed attempts, not exhaustive totals. The agent receives this limitation; the original shooter remains in raw telemetry for a future richer adapter.
- `possession_samples` contains seconds of **confirmed native ownership**, excluding loose balls and restarts. ETL calculates percentages; backend never does.
- Native v2 records actual taken corners, throw-ins, free kicks, penalties, goal kicks and kick-offs. A restart action can also be a pass or shot; adding those categories together double-counts actions.
- Fouls are **whistled native fouls**, not every contact or advantage played. Foul-won is a separate victim record. Offsides come from the referee decision, not an assumed free-kick cause. Cards retain yellow/second-yellow/red outcomes.
- Executed contact body parts identify headers, feet and other parts. Native pass/shot intent separates headed distribution from headed attempts; ambiguous headers remain touches. Incidental collisions keep body part unknown. A goal's body part follows the scoring contact, never an earlier shooter's limb.
- `body_part_event_types` certifies complete categories in this **immutable recording** only. Unknown contacts withdraw coverage; this is not a promise about future live data. General all-touch header totals can remain unavailable even when headed passes and shots are supported.
- Keeper claims come from transitions to retained goalkeeper possession. They are **not saves** without shot-outcome evidence. Successful tackles/interceptions, xG, on-target classification, woodwork, VAR, injuries and substitutions remain unavailable where there is no trustworthy telemetry. See the [event coverage catalogue](event-coverage.md). Rare events have explicit test fixtures; none are invented in the viewer's match.

`raw.jsonl.gz`, source video, styled video and final `match.mp4` remain ignored. The small delivery recording may be committed. Runtime rendering can change the simulation trajectory: the recording produced from the **rendered capture** is authoritative, never a separate headless seed run.

GRF source: [Google Research Football](https://github.com/google-research/football), Apache-2.0; Gameplay Football engine, Unlicense. Rendered upstream assets retain their original provenance; the simulator's asset rights are not a licence to real broadcast footage or official team branding.
