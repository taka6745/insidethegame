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

Benchmarks decompress it directly. Its expanded JSON exceeds the small browser lab's 2 MiB upload limit; do not upload the gzip file there. The 35-delivery fixture remains the lab default. This does not implement publishing to Event Hubs.

## Chelsea–Manchester United viewer recording

`chelsea-united-grf.json` is the **rendered** simulator capture used by the local ETL demo. It contains 1,321 deliveries across 12 playback minutes, mapped to 90 football minutes, and 22 illustrative real-name players. Final score: Chelsea 0–4 Manchester United. It replaces the unrelated authored product fixture; the benchmark recording above remains separate.

Native contact bursts are coalesced into actions. The delivery contract has 1,075 touches, 227 passes, 15 non-scoring shot attempts and 4 goals (scoring attempts). Measured ownership samples support possession; unavailable measurements are declared in `capabilities`. Source raw SHA-256 and limitations are embedded. Video and native raw telemetry stay in ignored `.local/grf-demo-chelsea-united-v2/`.

[Generate and package another match](../docs/grf-demo.md). The narrative demo service binds its authored stories to this recording's exact checksum; changing the match requires replacing those stories as well.
