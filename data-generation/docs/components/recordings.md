# Recordings (`recordings/`)

> **In short:** three rendered, tactically scripted 90-minute matches the [feed](feed.md) replays live. All are synthetic, simulated with [Google Research Football](../grf/README.md) (Apache-2.0), with invented players from [`league.json`](../../grf_demo/league.json). None is Stats Perform data or an actual match.

| | |
| --- | --- |
| **Status** | Shipped and tested; the feed serves all three |
| **Code** | [`recordings/`](../../recordings/) |
| **Contract** | [Opta-style event contract (v3)](../../contracts/README.md) |
| **Made by** | [grf-demo](grf-demo.md) (`generate-grf.sh`, `prepare-grf-source.sh`) |
| **Tests** | `tests/test_opta_stream.py`, `tests/test_fixture_recordings.py` (exports reproducible; Redcastle–Port Albion and Skybridge–Whitmore scores, scorers and totals pinned, with the ETL reference totals), `tests/test_recording.py` (Riverton–Forgeham) |

| Fixture | Score | Seed | Shot threshold |
| --- | --- | --- | --- |
| `riverton-forgeham` | 1–1 | 37 | 1.33 |
| `redcastle-portalbion` (main game) | 1–0 | 31 | 1.32 |
| `skybridge-whitmore` | 1–1 | 43 | 1.33 |

## 1. Files

*In short: one canonical recording per fixture, plus two derived exports.*

- `<fixture>-grf.json`: the canonical recording the feed loads.
- `<fixture>-grf.opta-f24.json`: the same match as an F24-style feed.
- `<fixture>-grf.opta-stream.jsonl`: that feed as the ETL's [Event Hubs MA1/MA3 messages](../../../etl/contracts/README.md) (team set-up rows become MA1 lineups; extra fields `videoSeconds`, `sourceEventId`, `possessionId`). Regenerate with `python -m grf_demo.opta_stream recordings/<fixture>-grf.json` from `data-generation/`. Its timestamps are nominal; a run rebases them to its kickoff.

The exports are kept for inspection and ETL tests; the feed builds its stream from the recording itself. Video, HLS segments and raw telemetry stay in ignored `.local/grf-demo-<fixture>-90/`.

## 2. Matches

*In short: score, scorers and render provenance; the tests hold the full totals.*

Each was rendered with the [realism patch](../../contracts/README.md#realism-patch) (`provenance.realism`), its own [tactics script](../../grf_demo/tactics.json) (`provenance.tactics`) and its own engine copy ([`prepare-grf-source.sh`](../../prepare-grf-source.sh)). Stall nudges are listed in `provenance.stall_nudge_seconds`. Rendering is deterministic for a given seed, engine and script.

**Riverton Rovers 1–1 Forgeham United.** Both goals were penalties: Callum Brightwell at 9:35 after Sami Lindqvist fouled in the box, and Rory Calloway at 71:16 after a foul by Yusuf Karabey. No cards. Riverton Rovers press and attack down the right, Forgeham play more directly down the left and tire from 70′. 11,133 deliveries; halves end at 45+1:18 and 90+1:06. Stall nudges at 1,700, 2,251, 2,717, 3,226 and 3,792 s. Rejected candidates scored 4–5 (threshold 1.33), 6–3, 2–4, 0–1, and 2–1 with only five attempts. Raw telemetry SHA-256 `a8a2f0d0…17736506` is embedded. The authored narrative fixtures (`narrative-engine/fixtures/`) describe an earlier render (Riverton Rovers 2–1), not this match.

**Redcastle Town 1–0 Port Albion.** Rafael Quintero scored at 46:09, in first-half stoppage; Elias Nordahl (13:23) and Dominik Hrabal (51:36) were booked. Port Albion wear their off-white away kit, press high and attack down the right, and tire from 70′. 10,902 deliveries; halves end at 45+1:18 and 90+1:20. One stall nudge, at 217.12 s.

**Skybridge City 1–1 Whitmore Wanderers.** Whitmore went ahead at 47:50 with a Joaquín Esteller own goal; Nathan Coyle equalised at 69:30. Jorge Palmeira was booked at 54:20 and sent off for a second yellow at 76:19; Lorenzo Castagna (15:24) and Lukas Halvorsen (48:54) were also booked. City press and attack down the left; Whitmore sit deeper, counter and tire late. 11,295 deliveries; halves end at 45+1:47 and 90+1:19. Stall nudges at 1,019, 2,590, 2,910 and 4,604 s. Rejected candidates scored 3–11 (seed 29, an earlier script at threshold 1.32) and 1–1 (seed 29, six yellows and few attempts).

Passes, recoveries, clearances, offsides and fouls run above top-flight norms and attempts and throw-ins below; these come from the simulation, not from rescaling ([not available](../../contracts/README.md#not-available)).
