# Devtools

> **In short:** one command-line tool, `python -m devtools`, for everything around the pipeline: start the local SQL and DAB stack, apply migrations, load a replay the way the cloud job would, verify Azure output against the reference, set up database users, and start or stop the billed Stream Analytics job (on Azure the stream schedule normally does this: [stream-analytics §6](stream-analytics.md#6-run-only-while-matches-play)).

| | |
| --- | --- |
| **Status** | Implemented · used throughout development |
| **Code** | [`devtools/__main__.py`](../../devtools/__main__.py), [`devtools/calibrate_trends.py`](../../devtools/calibrate_trends.py) |
| **Needs** | Docker (local stack), `sqlcmd`, Azure CLI and Terraform outputs (Azure commands) |
| **Secrets** | Local SA password generated into the ignored `.env`; Azure secrets from Terraform outputs, never printed |

## 1. Commands

*In short: local, verification and Azure groups.*

| Command | What it does |
| --- | --- |
| `local-up` | Write a random SA password to `.env`, start SQL Server and DAB (`docker-compose.yml`), apply migrations |
| `local-down [--wipe]` | Stop the stack (and delete its data) |
| `migrate [--azure SERVER]` | Apply `sql/migrations` locally, or to Azure with your `az login` |
| `load-local REPLAY.jsonl --window N` | Insert the rows the job would write and write notifications to `.local/notifications.jsonl` |
| `verify REPLAY.jsonl [--window N] [--graphql URL]` | Compare every GraphQL table and the view with the reference |
| `check-notifications REPLAY.jsonl [--window N]` | Peek the `narrative-engine` subscription and compare with the reference notifications |
| `azure-setup` | After `terraform apply`: migrations, `sql/azure` triggers, then database users and roles for the job, DAB (also `EXECUTE` on `statsAtSeq` and the trend procedures) and, once deployed, the purge API |
| `asa start\|stop\|status` | Control the Stream Analytics job; it bills only while running |
| `python -m devtools.calibrate_trends` | Print the trend thresholds (`notableAt`, `highAt`, `changeAt`) the shipped recordings give, for the newest `trendDefinitions` seed |

`--window N` is the tumbling window in seconds (60 ÷ replay speed; default 6, Azure real time 60).

## 2. Typical loops

*In short: offline loop and cloud loop.*

- **Offline:** `local-up` → `seeder.replay --target file` → `load-local` → `verify` (local GraphQL).
- **Cloud:** `asa start` → `seeder.replay --target eventhub` → `verify --graphql <dev url>` and `check-notifications` → `asa stop`.

`load-local` output is also what the narrative engine replays offline.
