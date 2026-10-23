# SPADL post-processor

> **In short:** converts each match's committed MA3 rows into standard SPADL actions (`dbo.spadlActions`), storing an action only once it is final, and advances `matchWatermarks.spadlSeq`. One piece of code: a thread in `etl-stream` locally, its own Container App (`ETL_ROLE=spadl`) on Azure. Stream Analytics is unchanged.

| | |
| --- | --- |
| **Status** | Implemented · unit-, parity- and SQL-tested (local and Azure schemas) · runs in the shared stack with three concurrent matches |
| **Code** | [`spadl/worker.py`](../../spadl/worker.py); rules in [`reference/spadl.py`](../../reference/spadl.py) |
| **Reads** | SQL `matchProgress` (watermark), `matches`, `rawEvents` (MA3 payloads with `eventSeq ≤` watermark), `purgedMatches` |
| **Writes** | `spadlActions`, `spadlProgress` (served as `matchWatermarks.spadlSeq`) |
| **Contract** | [ETL contracts: SPADL actions](../../contracts/README.md#output-3-spadl-actions), [schema](../../contracts/spadl-action.schema.json) |
| **Settings** | `ETL_SPADL_POLL_SECONDS` (0.5), `ETL_SPADL_MAX_POLL_SECONDS` (5), `ETL_SPADL_IDLE_SECONDS` (300); Azure: `ETL_EVENTHUB_CONNECTION_STRING` (listen) and `ETL_EVENTHUB_NAME` for the idle wake-up; SQL settings as [local stream](local-stream.md) |
| **Tests** | `test_spadl.py` (socceraction parity on 3 recordings, incremental = whole match, finalisation), `test_spadl_worker.py` (idle back-off and wake-up), `test_sql_catalogue.py`, `test_sql_azure.py` (SQL Server), `test_spadl_fixture.py` |

## 1. Loop

*In short: poll, convert the tail, store what is final, all in one transaction per match.*

```text
every 0.5 s, per match with matchProgress.seq P > spadlSeq:
  restart = last stored non-dribble action (or the first MA3 row)
  rows    = rawEvents from restart's MA3 seq with eventSeq ≤ P        (complete: P is the watermark)
  actions = reference.spadl.final_actions(rows, home, restart.actionId)
  INSERT actions with actionId > last stored; spadlProgress = P       (one transaction, multi-row inserts)
idle: the poll doubles up to 5 s; on Azure, after 300 s it closes SQL and only reads the hub's last enqueued
      sequence numbers (no SQL, nothing consumed) until a feed sends, so serverless SQL can auto-pause
```

- **Final only:** `final_actions` returns the prefix whose `finalSeq` is known, so stored rows never change and `actionId` never shifts. Restarting from the last stored action recomputes it identically, because the rules only look ahead.
- **Stateless:** a restart or a second replica recomputes the same rows; the primary key ignores duplicates.
- **Purge:** writes hold applock `etl-purge` shared and skip a match that is tombstoned or gone, so a step that read before a purge writes nothing. The purge deletes `spadlActions` and `spadlProgress` with the match's other rows.

## 2. Deployment

*In short: same image as the purge API.*

| Where | How |
| --- | --- |
| Local stack | `etl-stream` starts the thread (`spadl_worker.start`) beside the stream worker |
| Azure | [`infra/spadl.tf`](../../infra/spadl.tf): Container App `…-spadl`, 1 replica, no ingress, managed identity to Azure SQL; created with `admin_image_tag`; `devtools azure-setup` grants `db_datareader`/`db_datawriter`. Idle wake-up through the hub's `spadl-listen` rule, so the serverless database can auto-pause between matches (60 min delay) |
