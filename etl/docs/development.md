# Development

> **In short:** Docker runs the two pieces that have local equivalents (SQL Server for Azure SQL, Data API builder itself). Stream Analytics and the messaging services have no local emulator, so the Python reference implementation produces their output and files stand in for Event Hubs and Service Bus.

| | |
| --- | --- |
| **Needs** | Python 3.11, Docker Desktop, `sqlcmd`, Node (UDF tests); Azure CLI and Terraform for Azure work |
| **Settings** | Ignored `etl/.env` (local SA password, generated) |
| **Tests** | `pytest tests` (77 pass; the 14 SQL Server tests skip without `ETL_TEST_SQL_PASSWORD`, the UDF tests without Node; about 3 minutes with them on an emulated SQL Server) plus `devtools verify` end to end |
| **Whole product locally** | `ACCEPT_EULA=Y ./dev up backend` runs this pipeline's SQL schema and DAB config with the [local stream](components/local-stream.md) worker in place of Stream Analytics (`etl-stream`, GraphQL `http://localhost:15001/graphql`), read by the backend and the narrative engine: [../../DEVELOPMENT.md](../../DEVELOPMENT.md) |

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

**Test:** install `requirements-test.txt`, then `python -m pytest tests`. For the SQL tests, point `ETL_TEST_SQL_PASSWORD` (and `ETL_TEST_SQL_HOST`/`PORT`) at a throwaway SQL Server; unit tests use repository doubles and do not claim database coverage. The `Dockerfile` builds the local stream image (`--target stream`), which Azure also runs as the purge API (`ETL_ROLE=admin`).

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
| `test_udfs.py` | The Stream Analytics JavaScript UDFs run in Node and agree with the Python rules; each generated `udfs/*.js` equals its compiled `udfs/src/*.ts` (skips without Node / `tsc`) |
| `test_azure_parity.py` | On all three recordings: the reference (Stream Analytics rows, marks → watermark and status) equals the local stream worker row for row and along the match; the row UDFs equal the reference |
| `test_local_stream.py` | The [local stream](components/local-stream.md): matches the reference on the GRF stream, window closing, redelivery, restart, failed commits; MatchEvent v2 + POS rows, watermark and status, MA1 gate and cut-off, purge (API, restart, redelivery), two interleaved matches; a restored seed carries on as if never stopped; seed routes mounted only with `DEMO_SEEDS=1` |
| `test_spadl.py` | `reference/spadl.py` equals socceraction 1.5.3 (MA3JSONParser → convert_to_actions → SPADLSchema; test-only, pinned in `requirements-test.txt`) on all three recordings with an empty allow-list (a goal with an unknown scorer passes SPADLSchema with a placeholder player); incremental conversion at every watermark equals whole-match; shots final at once, `period_end` finalises its period; extensions and zones |
| `test_spadl_worker.py` | The post-processor loop: idle polls back off; with an activity check (Azure: Event Hubs) it closes SQL after the idle time and wakes when the hub receives |
| `test_spadl_fixture.py` | `tests/fixtures/spadl-riverton-forgeham.json` (the rows backend and engine tests build on) is the current conversion; the JSON schema lists every column |
| `test_catalogue.py` | `reference/catalogue.py` on SPADL equals `tests/fixtures/catalogue-golden.json` for all 126 stats at the final seq and 20 prefixes; old ids kept in order; snapshots count only final actions |
| `test_catalogue_rules.py` | Counting rules on small SPADL inputs: own goals and fouls won for the other team, VAR overturns (goals and own goals) from their seq, pass family and set pieces, on target vs blocked, entries, body-part availability, final-only snapshots, MA3 cards, retired kinds |
| `test_trends.py` | `reference/trends.py` on small inputs (ball timeline, entries, fast breaks, MA3 components, windows and flags, disabled trends, spells, momentum, bounds, newest seed block) and on Riverton Rovers–United against `tests/fixtures/trends-golden.json` (`python tests/test_trends.py --regenerate` after a deliberate change or a re-rendered recording) |
| `test_sql_trends.py` | Real SQL Server: the three trend procedures equal the reference on all three recordings at 10 seqs (expected values computed from the recordings), empty above `spadlSeq` or the watermark, the table equals the seed and a re-seed changes flags, full-time calls under 500 ms |
| `test_sql_catalogue.py` | Real SQL Server: migrations, stream worker and SPADL post-processor; `spadlActions` equal the whole-match conversion and, at 10 intermediate seqs, exactly the actions final there; `statsAtSeq` equals the golden values and the reference (empty above `spadlSeq`), also with VAR overturns; purge leaves 0 rows (SPADL included), survives restart + redelivery and a stale post-processor write; purge all; interleaved matches. Needs a disposable server: `ETL_TEST_SQL_PASSWORD` (and `ETL_TEST_SQL_HOST`/`PORT`); each run creates and drops its own databases |
| `test_sql_seeds.py` | Real SQL Server: a held run's seed exported, purged and restored under a new matchId equals the recorded rows and carries on to the same rows as an uninterrupted run; refusals (other schema, known match, rows past the seq) |
| `test_sql_azure.py` | Real SQL Server with `sql/azure`: the job's rows as independent, reordered and parallel output batches give the reference watermark, status and (after the SPADL post-processor) `statsAtSeq`; purge, tombstones and the purge-all cut-off hold against later inserts and post-processor steps |

The SQL view and the deployed query are checked end to end by `devtools verify` and `check-notifications`, locally and in Azure.

## 5. Conventions

*In short: change rules in pairs, keep secrets out of Git.*

- A rule change touches the query (`stream-analytics/`) and the reference (`reference/`) together; the view (`sql/`) and `reference/pipeline.py stats_as_of` likewise.
- UDFs are TypeScript in `stream-analytics/udfs/src/`; `./dev udfs` (or `node stream-analytics/udfs/build.ts`) regenerates the `.js` Terraform uploads. Never edit the `.js`.
- Generated data is labelled `synthetic: true` with provenance.
- `.env`, `.local/`, Terraform state and `local.auto.tfvars` are ignored.
