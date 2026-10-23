# GRF full-match benchmark recording (archived)

> **In short:** an older derived recording no active code reads, kept for provenance. Synthetic, simulated with [Google Research Football](../data/GoogleResearchFootball/README.md) (Apache-2.0); not Stats Perform data or an actual match.

`grf-full-match.json.gz` contains **14,018 deliveries across 90 simulated minutes and 22 players**. It is a small derived recording from a local GRF run, not a live simulation or licensed Opta feed.

| Source | Conversion |
| --- | --- |
| GRF `ball_touch` | `touch`; head qualifier only when explicitly recorded |
| `pass_result` | `pass`, completion outcome, horizontal displacement |
| `shot` | `shot` with recorded actor |
| `goal` | `goal` with last-touch actor, not a certified scorer |

Touches and inferred actions are separate telemetry records; don't read their combined count as official football events. No invented corners, cards, tackles or saves; the run has no recorded header contacts. Source checksum, counts and limitations are embedded in the recording. Original raw telemetry and footage remain ignored and unmodified.

Reproduced from the original local export with `grf_recording.py` (its embedded `converter` path is the file's location before it was archived):

```sh
python3 legacy/data-generation/grf_recording.py \
  .local/grf-runs/full-90m-4k/data/events.jsonl.gz \
  legacy/data-generation/grf-full-match.json.gz
```
