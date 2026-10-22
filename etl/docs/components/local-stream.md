# Local stream

> **In short:** a Python stand-in for the Stream Analytics job, used only by the shared local Docker stack. It reads MA1, MA3, POS and canonical `MatchEvent` v2 messages from Event Hubs, applies the [reference rules](reference.md) one message at a time, writes the job's SQL tables plus the multi-match read models, and sends the same notifications to Service Bus. Consumers read them through Data API builder, including the stat catalogue (`executeStatsAtSeq`).

| | |
| --- | --- |
| **Status** | Implemented · unit- and SQL-tested · run in the local stack (`./dev up backend`) · not deployed as a worker (Azure runs the real job, equal by test on all three recordings: `test_azure_parity.py`). The same image's purge API is the Azure admin app (`infra/admin.tf`; applied 22 Oct). Demo seed routes: implemented and SQL-tested, `DEMO_SEEDS=1` only |
| **Code** | [`local_stream/`](../../local_stream/) (worker, processor, repository, SDK adapters, `state.sql`, `init-sql.sh`) |
| **Image** | [`Dockerfile`](../../Dockerfile), compose service `etl-stream`; DAB `/health` (anonymous) backs the `etl-dab` healthcheck |
| **Reads** | Event Hubs `match-events`, consumer group `stream-analytics`: MA1, MA3, POS, `MatchEvent` v2 |
| **Writes** | SQL Server database `insidethegame`: `matches` (+ `matchTeams`, `matchPlayers`), `canonicalEvents`, `possessionSamples`, `rawEvents`, `keyEvents`, `minuteStats`, `matchProgress` (watermarks), `purgedMatches`; `spadlActions`, `spadlProgress` (its [SPADL](spadl.md) thread); Service Bus `match-notifications` |
| **Serves (via `etl-dab`)** | `http://localhost:15001/graphql` (host), `http://etl-dab:5000/graphql` (Docker) |
| **Tests** | `test_local_stream.py`, `test_sql_seeds.py`, `test_catalogue.py`, `test_sql_catalogue.py` (SQL Server; skips without `ETL_TEST_SQL_PASSWORD`); `local/etl_stream_check.py` in `./dev test backend` |

## 1. Flow

*In short: the same tables and notifications as the job, from one Python process.*

```text
feed run ─ MA1/MA3/POS/MatchEvent v2 ─→ Event Hubs ─→ etl-stream ─→ SQL insidethegame ─→ etl-dab GraphQL ─→ engine, backend
                                              └─ outbox ─→ Service Bus match-notifications (narrative-live) ─┘
```

- **Input:** per run, MA1, then each canonical `MatchEvent` v2 followed by its MA3 rows, with POS samples interleaved ([contracts](../../contracts/README.md)). Messages are told apart by `feed` (MA1/MA3/POS) or `type: MatchEvent, version: 2` (no `feed`). MA3, POS and `MatchEvent` are accepted only for a match whose MA1 is stored; redeliveries are skipped by MA3 id, `seq` and `sampleId`.
- **Watermark:** event *s* is complete once anything else arrives for its match (its MA3 rows come straight after it), or after `ETL_WATERMARK_IDLE_SECONDS` (3 s) of quiet. `matchProgress` holds it; the `matchWatermarks` view joins its event. `status` goes `scheduled` → `live` (first event) → `finished` (watermark reaches the final `period_end`).
- **SPADL:** a second thread runs the [SPADL post-processor](spadl.md) on its own connection: committed MA3 rows → `spadlActions`, `matchWatermarks.spadlSeq`.
- **Stat catalogue:** `statsAtSeq(@matchId, @seq)` counts SPADL actions, MA3 card rows and POS samples by the `statDefinitions` rows ([SQL](sql.md)); it is empty above the watermark or `spadlSeq`.
- **Admin (`ETL_ADMIN_PORT`, default 8000):** `GET /health`; `POST /admin/matches/purge` with `{"match_id": …}` or `{"all": true}` ([purge contract](../../../local/contracts.md#5-purge)). It writes the tombstone (`purgedMatches`; `all` also sets `purgeCutoff`), then deletes the match's rows, progress, window and outbox in the same transaction; checkpoints and `statDefinitions` stay. Tombstones survive restarts, so redelivered messages never recreate the match. On Azure the image runs with `ETL_ROLE=admin`: only this API, against Azure SQL with its managed identity (`ETL_SQL_AUTH=managed-identity`, driver `mssql-python`), POST behind `Authorization: Bearer $ETL_ADMIN_TOKEN`; Azure SQL's triggers enforce the tombstones ([SQL §5](sql.md#5-azure-only-stream-analytics-rows)).
- **Windows:** 60-second event-time tumbling windows. A minute closes when the next minute's first event arrives, or after 75 s without messages for that match (paused run, full time).
- **Notifications:** `MinuteClosed`, `KeyEventDetected`, `PeriodStarted`, `PeriodEnded`, with `notificationType` for the `narrative-live` subscription filter.

## 2. Recovery

*In short: one transaction per batch, so a restart neither loses nor double-counts.*

Rows, closed windows, watermarks, the Event Hubs checkpoint and the outbox commit together (`state.sql` tables `localStreamCheckpoints`, `localStreamWindows`, `localStreamOutbox`). A failed commit or load discards in-memory state, reconnects to SQL and resumes from the checkpoint; a restart rebuilds open windows from SQL. The outbox sender sets `MessageId`, so resends are dropped. Without a checkpoint the consumer starts two minutes before now, so old runs in retention are not replayed; a checkpoint past the partition's end (a recreated hub, e.g. the emulator) is treated the same way, checked at connect and every 5 s while connected (logged, the stored checkpoint deleted, then a reconnect). Canonical seqs must arrive without holes: after a lost event (such a reset) the match's later `MatchEvent`s are dropped with one warning, so its watermark stays before the hole instead of counting a partial history. A malformed message (envelope or body) is logged and dropped, as the Azure job's `Drop` error policy does, rather than block its partition. Rows are inserted many per statement. `init-sql.sh` applies `sql/migrations` and `state.sql` once each.

## 3. Limits

*In short: a stand-in for the demo, not the production pipeline.*

One worker process, one SQL round trip per row: about 50 messages/s on the emulated local SQL Server, well above a live match (~3.5/s). A late event joins the next window, like the job's adjust policy. Settings: `ETL_ROLE`, `ETL_ADMIN_TOKEN`, `ETL_SQL_AUTH`, `ETL_SQL_*`, `ETL_EVENTHUB_*`, `ETL_SERVICEBUS_CONNECTION_STRING`, `ETL_NOTIFICATIONS_TOPIC`, `ETL_WINDOW_SECONDS`, `ETL_IDLE_SECONDS`, `ETL_WATERMARK_IDLE_SECONDS` (see [`__main__.py`](../../local_stream/__main__.py)).

## 4. Demo seeds (`DEMO_SEEDS` only)

*In short: a demo-only adapter on the admin API exports one match's rows and restores them under a new matchId.*

[`demo_seeds.py`](../../local_stream/demo_seeds.py) adds two routes to the admin server when `DEMO_SEEDS=1` (local compose; the judge build's admin app); without it they do not exist. Authorised like the purge.

| Route | Does |
| --- | --- |
| `GET /admin/matches/export?match_id=` | `{match_id, schema, tables}`: every match table's rows (events, SPADL, trend inputs, progress, windows) and a fingerprint of their columns |
| `POST /admin/matches/restore {match_id, max_seq, schema, tables}` | One transaction, then the worker reloads its state from SQL (as after a restart). `409` for another schema, a known or tombstoned match, rows of another match or past `max_seq`; `413` over 512 MB |

Demo control records a seed from a *held* feed run and restores it before releasing the new run, which then sends only what follows: the rows equal one uninterrupted run (`test_sql_seeds.py`). Rows go in the shapes the stream writes; no core code knows a demo exists ([PLAN.md §10.6](../../../PLAN.md)).
