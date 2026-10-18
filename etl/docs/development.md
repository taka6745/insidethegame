# Develop match data

```text
GRF recording → ETL demo → history database
                       → statistics database → GraphQL → backend / narrative stub
```

The runnable adapter lives in `demo_etl/`. HTTP routes call `MatchService`; repositories own connections; `RecordingSource` owns provider keys. Keep the future Azure implementation separate and preserve these read contracts.

**Run:** `uvicorn demo_etl.app:from_env --factory --port 8000` from this folder. Set `ETL_HISTORY_DATABASE_URL`, `ETL_STATS_DATABASE_URL` to two local PostgreSQL databases and `DEMO_RECORDING_PATH` to the generated recording. Docker uses the same entry point. See root development commands for the integrated stack.

**Test:** install `requirements-test.txt`, then `PYTHONPATH=. pytest tests`. Set `ETL_TEST_HISTORY_DATABASE_URL` and `ETL_TEST_STATS_DATABASE_URL` to disposable PostgreSQL databases to include persistence/restart tests. Unit tests use repository doubles; they do not claim database coverage.

**Inspect:** history DB views `raw_recording_events` (unaltered source JSON), `raw_event_history` (observed canonical deliveries); stats DB view `standard_stats` (per snapshot/team/metric). Full recordings are stored once. History deliveries are stored once per run; snapshots retain watermarks, not duplicate event arrays.

**Publication:** history commits first, then the separately stored projection. No success is returned until both exist. A failed second write is repaired by retrying the same immutable snapshot; reads fail closed while incomplete. The demo recomputes small match projections during ingestion, never on standard-stat reads. It is not a distributed stream-processing implementation.

**Production:** Azure SQL history, Cosmos stat state, Event Hubs ingestion and Stream Analytics aggregation remain the planned adapters. Preserve revision/tombstone handling and readable-state-before-notification. The metadata cursor bridge is explicitly local; it does not replace production brokers. No cloud apply or scheduled automation is part of this setup.
