# Recordings

> **In short:** three rendered, tactically scripted 90-minute matches the [feed](../docs/components/feed.md) replays live, plus one older benchmark recording. All are synthetic, simulated with [Google Research Football](../../legacy/data/GoogleResearchFootball/README.md) (Apache-2.0), with illustrative real-name lineups. None is Stats Perform data or an actual match.

| Fixture | Files | Score | Seed |
| --- | --- | --- | --- |
| `chelsea-united` | `chelsea-united-grf.json`, `.opta-f24.json`, `.opta-stream.jsonl` | 1–1 | 37 |
| `arsenal-liverpool` | `arsenal-liverpool-grf.*` (same three) | 1–0 | 31 |
| `mancity-tottenham` | `mancity-tottenham-grf.*` (same three) | 1–1 | 43 |
| benchmark only | `grf-full-match.json.gz` | n/a | n/a |

`<fixture>-grf.json` is the canonical recording the feed loads. The `.opta-f24.json` and `.opta-stream.jsonl` exports are derived from it, kept for inspection and ETL tests; the feed builds its stream from the recording itself. `tests/test_opta_stream.py` and `tests/test_fixture_recordings.py` check the exports are reproducible and pin the facts below.

## Reusable full match

`grf-full-match.json.gz` contains **14,018 deliveries across 90 simulated minutes and 22 players**. It is a small derived recording from the existing local GRF run, not a new live simulation or licensed Opta feed.

| Source | Conversion |
| --- | --- |
| GRF `ball_touch` | `touch`; head qualifier only when explicitly recorded |
| `pass_result` | `pass`, completion outcome, horizontal displacement |
| `shot` | `shot` with recorded actor |
| `goal` | `goal` with last-touch actor, not a certified scorer |

Touches and inferred actions are separate telemetry records; don't interpret their combined count as official football events. No invented corners, cards, tackles or saves. The original run has no recorded header contacts; hand-authored lab fixtures cover those, corrections and exact edge cases. Source checksum, counts and limitations are embedded in the recording. GRF is Apache-2.0; see the [archived simulator and provenance](../../legacy/data/GoogleResearchFootball/README.md). Original raw telemetry/footage remain ignored and unmodified.

Reproduce from the original local export:

```sh
python3 data-generation/grf_recording.py \
  .local/grf-runs/full-90m-4k/data/events.jsonl.gz \
  data-generation/recordings/grf-full-match.json.gz
```

Only the backend performance benchmark reads it (decompressing directly). The feed does not serve it: it has no Opta-style events or video.

## Chelsea–Manchester United viewer recording

*In short: the demo's main match, rendered 2026-10-22 with scripted tactics.*

`chelsea-united-grf.json` is the **rendered**, real-time simulator capture used by the local demo and most tests: one 90-minute match with a broadcast clock (first half to 45+1:18, second to 90+1:06), 22 illustrative real-name players and 11,133 deliveries in the [Opta-style v3 contract](../docs/opta-events.md). `chelsea-united-grf.opta-f24.json` is the same match as an F24-style feed (2,377 rows). `chelsea-united-grf.opta-stream.jsonl` is that feed as the ETL's [Event Hubs MA1/MA3 messages](../../etl/contracts/README.md) (1 MA1 + 2,375 MA3; team set-up rows become MA1 lineups; extra fields `videoSeconds`, `sourceEventId`, `possessionId`), regenerated with `python -m grf_demo.opta_stream recordings/chelsea-united-grf.json` from `data-generation/`. Its timestamps are nominal; on a run the feed rebases them to the run's kickoff and sends each event's rows right after that event's `MatchEvent`. Both are synthetic and labelled so; neither is Stats Perform data.

**Chelsea 1–1 Manchester United.** Both goals were penalties: Kobbie Mainoo scored at 9:35 after Reece James fouled in the box, and Andrey Santos equalised at 71:16 after a foul by Matheus Cunha. No cards.

Script ([`tactics.json`](../grf_demo/tactics.json), `provenance.tactics`): Chelsea press and attack down the right, United play more directly and down the left; spells of pressure alternate (Chelsea 3–13′, 33–45′, 61–72′; United 18–28′, 46–56′); United tire from 70′; from 58′ the team ahead sits deep while the other pushes, and from 75′ a trailing team goes all out.

| | Chelsea | Man Utd |
| --- | --- | --- |
| Attempts (on target) | 9 (3) | 5 (2) |
| Goalkeeper saves | 1 | 3 |
| Passes (accuracy) | 940 (80%) | 460 (73%) |
| Possession (confirmed ownership) | 64% | 36% |
| Corners / fouls / cards / offsides | 2 / 19 / 0 / 2 | 3 / 11 / 0 / 3 |

Whole match: 9 non-scoring attempts off target and 3 saved, 37 interceptions, 25 tackles, 98 clearances, 80 aerial records, 433 ball recoveries. Attempts and throw-ins (9) run below Premier League norms, and recoveries, clearances and passes above. These differences come from the simulation, not from rescaling ([details](../docs/opta-events.md#not-available)).

It was rendered from seed 37 with the [realism patch](../docs/opta-events.md#realism-patch) (shot threshold 1.33). Five stall nudges, at 1,700, 2,251, 2,717, 3,226 and 3,792 video seconds, are listed in `provenance.stall_nudge_seconds`. Rejected candidates scored 4–5 (shot threshold 1.32), 6–3, 2–4, 0–1, and 2–1 with only five attempts.

Raw telemetry SHA-256 `40e22b77…5914f18c` is embedded. Video, HLS segments and raw telemetry stay in ignored `.local/grf-demo-chelsea-united-90/`. The authored narrative fixtures (`narrative-engine/fixtures/`) describe the previous render (Chelsea 2–1, kept in `narrative-engine/fixtures/archive/`), not this match. [Generate and package another match](../docs/components/grf-demo.md).

## Concurrent-demo recordings

*In short: two more scripted, rendered 90-minute matches, so several fixtures can run at once.*

Both were made the same way as Chelsea–United: same realism settings (Arsenal–Liverpool at shot threshold 1.32, the rest at 1.33; `provenance.realism`), each fixture's own [tactics script](../grf_demo/tactics.json), real-name 2025/26 lineups ([`roster.py`](../grf_demo/roster.py)) and each fixture's own engine copy ([`prepare-grf-source.sh`](../prepare-grf-source.sh)). Each has `<fixture>-grf.json`, `.opta-f24.json` and `.opta-stream.jsonl`. All are synthetic, labelled as such, and simulated with [Google Research Football](../../legacy/data/GoogleResearchFootball/README.md) (Apache-2.0). None is Stats Perform data or an actual match. Video, HLS and raw telemetry stay in ignored `.local/grf-demo-<fixture>-90/`; `native.mp4` was removed after packaging.

**Arsenal 1–0 Liverpool** (`arsenal-liverpool`, seed 31). Liverpool wear their off-white away kit. Script: Liverpool press high and attack down the right; Arsenal play more directly; spells of pressure alternate; Liverpool tire from 70′. Viktor Gyökeres scored at 46:09, in first-half stoppage. Martín Zubimendi (13:23) and Florian Wirtz (51:36) were booked. The halves end at 45+1:18 and 90+1:20. 10,902 deliveries; F24 has 2,428 rows; the stream has 1 MA1 + 2,426 MA3. One stall nudge, at 217.12 s.

| | Arsenal | Liverpool |
| --- | --- | --- |
| Attempts (on target) | 10 (5) | 8 (2) |
| Goalkeeper saves | 2 | 5 |
| Passes (accuracy) | 628 (73%) | 745 (78%) |
| Possession (confirmed ownership) | 51% | 49% |
| Corners / fouls / cards / offsides | 2 / 13 / 1 / 5 | 1 / 13 / 1 / 11 |

**Manchester City 1–1 Tottenham Hotspur** (`mancity-tottenham`, seed 43). Script: City press, keep the ball and attack down the left; Spurs sit deeper and counter, come out after half time and tire late. Spurs went ahead at 47:50 with a Rúben Dias own goal (City's last touch); Nico O'Reilly equalised at 69:30. Bernardo Silva won a free kick at 22:37 on the edge of the box (the referee did not give a penalty). João Palhinha was booked at 54:20 and sent off for a second yellow at 76:19; Bernardo Silva (15:24) and Lucas Bergvall (48:54) were also booked. The halves end at 45+1:47 and 90+1:19. 11,295 deliveries; F24 has 2,575 rows; the stream has 1 MA1 + 2,573 MA3. Stall nudges at 1,019, 2,590, 2,910 and 4,604 s.

| | Man City | Spurs |
| --- | --- | --- |
| Attempts (on target) | 9 (4) | 1 (0) |
| Goalkeeper saves | 0 | 4 |
| Passes (accuracy) | 1,010 (80%) | 478 (72%) |
| Possession (confirmed ownership) | 63% | 37% |
| Corners / fouls / cards / offsides | 4 / 22 / 1 / 5 | 3 / 11 / 3 / 3 |

Rendering is deterministic for a given seed, engine and script. Rejected City candidates scored 3–11 (seed 29, an earlier script at threshold 1.32) and 1–1 (seed 29, six yellows and few attempts). Offsides and fouls run above Premier League norms, and attempts below; these come from the simulation. `tests/test_fixture_recordings.py` pins these facts and the ETL reference totals.
