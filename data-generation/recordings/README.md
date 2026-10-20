# Reusable full match

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

Benchmarks decompress it directly. Its expanded JSON (~3.3 MB) fits the browser lab's 16 MiB upload limit; upload the expanded file, not the gzip. The 35-delivery fixture remains the lab default. This does not implement publishing to Event Hubs.

## Chelsea–Manchester United viewer recording

`chelsea-united-grf.json` is the **rendered**, real-time simulator capture used by the local demo: one 90-minute match with a broadcast clock (first half to 45+0:57, second to 90:58), 22 illustrative real-name players and 11,392 deliveries in the [Opta-style v3 contract](../docs/opta-events.md). `chelsea-united-grf.opta-f24.json` is the same match as an F24-style feed (2,625 rows). Both are synthetic and labelled so; neither is Stats Perform data.

**Chelsea 2–1 Manchester United.** Reece James scored at 27:12 and 66:55; Benjamin Šeško equalised in between, at 60:40. Kobbie Mainoo's second yellow at 51:18 left United with ten men.

| | Chelsea | Man Utd |
| --- | --- | --- |
| Attempts (on target) | 16 (9) | 8 (3) |
| Goalkeeper saves | 2 | 7 |
| Passes (accuracy) | 864 (76%) | 627 (78%) |
| Possession (confirmed ownership) | 53% | 47% |
| Corners / fouls / cards / offsides | 3 / 5 / 0 / 1 | 3 / 9 / 4 / 0 |

Whole match: 21 non-scoring attempts (11 off target, 9 saved, 1 blocked), 33 interceptions, 46 tackles, 105 clearances, 86 aerial records, 503 ball recoveries. Recoveries, clearances and passes run above Premier League norms, and throw-ins (19) and offsides (1) below. These differences come from the simulation, not from rescaling ([details](../docs/opta-events.md#not-available)).

It was rendered from seed 37 with the [realism patch](../docs/opta-events.md#realism-patch). One stall nudge, at 2,136 video seconds, is listed in `provenance.stall_nudge_seconds`. Earlier candidates were rejected: seed 7 froze, seed 11 stalled, and seeds 29 and 31 scored 3–3 and 3–2. In headless validation over full matches, the same settings gave 1–10 goals and 12–37 attempts per match.

Raw telemetry SHA-256 `513b27bb…d019ae03d` is embedded. Video, HLS segments and raw telemetry stay in ignored `.local/grf-demo-chelsea-united-90/`. The narrative service binds its authored stories to this file's exact checksum, so changing the match requires replacing them too. [Generate and package another match](../docs/grf-demo.md).
