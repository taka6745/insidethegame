# Seeder

> **In short:** generates a synthetic Opta match that exercises every key event, and replays any match file onto Event Hubs (or into a timestamped file) at a chosen speed, lined up with Stream Analytics windows. Temporary: data generation will supply real generated matches later.

| | |
| --- | --- |
| **Status** | Implemented · tested · used for every dev replay |
| **Code** | [`seeder/`](../../seeder/): `generate.py`, `replay.py`, `matches/itg-syn-0001.jsonl` |
| **Data** | SYNTHETIC: invented teams, players and events, `synthetic: true` with provenance |
| **Depends on** | [reference](reference.md) `opta` codes |
| **Tests** | `test_seeder_and_pipeline.py`, `test_udfs.py` |

## 1. Generator (`generate.py`)

*In short: a seeded, scripted match with every key event type.*

```sh
python -m seeder.generate --seed 7 --out seeder/matches/itg-syn-0001.jsonl
```

- Teams Riverside FC (home) and Harbour Athletic (away), 14-player squads, 2 and 4 added minutes.
- Background play (passes, shots, fouls, corners, cards) from a seeded random generator.
- Scripted moments: a goal, a missed penalty, a VAR goal overturn, a second-yellow red card, a scored penalty and an own goal. Final score 1-2.
- Output: one MA1 message, then MA3 events, one JSON object per line.

## 2. Replay (`replay.py`)

*In short: rewrite timestamps for now, align periods to windows, send.*

```sh
python -m seeder.replay seeder/matches/itg-syn-0001.jsonl --speed 10 --target eventhub --match-id demo1
```

| Option | Effect |
| --- | --- |
| `--speed` | Match seconds per wall second; must divide 60 (10 gives 6-second minutes) |
| `--match-id` | Default: the file's matchId plus a UTC suffix, so reruns are new matches |
| `--half-time-seconds` | Wall-clock gap between periods (default 30) |
| `--target eventhub\|file` | Send to Event Hubs, or only write the file |
| `--out` | File path (default `.local/replays/<matchId>.jsonl`) |

Each period starts half a match second after a window boundary, so every match minute falls inside exactly one window. A timestamped copy is always written, because `devtools verify` needs exactly what was sent.

Event Hubs auth: `ETL_EVENTHUB_CONNECTION_STRING` (send-only key from Terraform), or `ETL_EVENTHUB_NAMESPACE` with your Azure login.
