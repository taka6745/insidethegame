# Development

> **In short:** Docker runs the two pieces that have local equivalents (SQL Server for Azure SQL, Data API builder itself). Stream Analytics and the messaging services have no local emulator, so the Python reference implementation produces their output and files stand in for Event Hubs and Service Bus.

| | |
| --- | --- |
| **Needs** | Python 3.11, Docker Desktop, `sqlcmd`, Node (UDF tests); Azure CLI and Terraform for Azure work |
| **Settings** | Ignored `etl/.env` (local SA password, generated) |
| **Tests** | `pytest tests` (54 pass, 1 skip without PostgreSQL: 7 pipeline, 47 stand-in) plus `devtools verify` end to end |
| **Whole product locally** | The shared Docker stack runs the [stand-in](components/demo-etl.md), not this pipeline: [../../DEVELOPMENT.md](../../DEVELOPMENT.md) |

## 1. Setup

*In short: a virtual environment and the Docker stack.*

```sh
cd etl
python -m venv .venv && .venv/Scripts/pip install -r requirements-test.txt   # requirements.txt plus pytest; Windows path shown
.venv/Scripts/python -m pytest tests
.venv/Scripts/python -m devtools local-up        # SQL Server + DAB in Docker, GraphQL on :5000
```

## 2. Local stand-ins

*In short: Docker where a real local version exists, Python and files elsewhere.*

| Azure piece | Local stand-in |
| --- | --- |
| Azure SQL | SQL Server 2025 container (`docker-compose.yml`), port 14330 |
| Data API builder | The same DAB image and config in Docker, port 5000 |
| Event Hubs | `seeder.replay --target file` writes the replay to `.local/replays/` |
| Stream Analytics | `reference/pipeline.py`, run by `devtools load-local`, which inserts the expected rows |
| Service Bus | `load-local` writes notifications to `.local/notifications.jsonl` |

**Test:** install `requirements-test.txt`, then `PYTHONPATH=. pytest tests`. `tests/test_opta_v3.py` covers the v3 contract (new types/qualifiers, stoppage-time clock, new stats) with small synthetic inputs. Set `ETL_TEST_HISTORY_DATABASE_URL` and `ETL_TEST_STATS_DATABASE_URL` to disposable PostgreSQL databases to include persistence/restart tests. Unit tests use repository doubles; they do not claim database coverage. Docker builds use `--target runtime` for the service and `--target test` for pytest; the runtime excludes tests and test dependencies.

The SQL Server 2022 image failed on this machine; 2025-CU9 works. Docker Desktop hangs if the C: drive fills, so check free space first.

## 3. The offline loop

*In short: replay to a file, load it, verify it.*

```sh
.venv/Scripts/python -m seeder.replay seeder/matches/itg-syn-0001.jsonl --speed 10 --target file --match-id demo
.venv/Scripts/python -m devtools load-local .local/replays/demo.jsonl --window 6
.venv/Scripts/python -m devtools verify .local/replays/demo.jsonl --window 6
```

`verify` queries every GraphQL entity and the view and compares them with the reference, row by row. The notifications file is what the narrative engine replays offline.

## 4. Tests

*In short: rules and UDFs are tested without Azure.*

| File | Covers |
| --- | --- |
| `test_seeder_and_pipeline.py` | Generated match content, replay scheduling and windows, reference outputs (key events, deltas, notifications, running totals) |
| `test_udfs.py` | The Stream Analytics JavaScript UDFs run in Node and agree with the Python rules (skips without Node) |
| `test_etl.py`, `test_brokers.py`, `test_native_events.py` | The [stand-in](components/demo-etl.md): snapshots, GraphQL, broker mode, native GRF events (Postgres tests skip without `ETL_TEST_*_DATABASE_URL`) |

The SQL view and the deployed query are checked end to end by `devtools verify` and `check-notifications`, locally and in Azure.

## 5. Conventions

*In short: change rules in pairs, keep secrets out of Git.*

- A rule change touches the query (`stream-analytics/`) and the reference (`reference/`) together; the view (`sql/`) and `reference/pipeline.py stats_as_of` likewise.
- Generated data is labelled `synthetic: true` with provenance.
- `.env`, `.local/`, Terraform state and `local.auto.tfvars` are ignored.
