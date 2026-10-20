# Develop match data

```text
Replay → Event Hubs → ETL demo → history + statistics → GraphQL
                              → Service Bus snapshot-ready notification
```

The runnable adapter lives in `demo_etl/`. HTTP routes call `MatchService`; repositories own connections; `RecordingSource` owns provider keys. Keep the future Azure implementation separate and preserve these read contracts.

**Run:** `uvicorn demo_etl.app:from_env --factory --port 8000` from this folder. Set `ETL_HISTORY_DATABASE_URL`, `ETL_STATS_DATABASE_URL` to two local PostgreSQL databases and `DEMO_RECORDING_PATH` to the generated recording. Docker uses the same entry point. See root development commands for the integrated stack.

**Test:** install `requirements-test.txt`, then `PYTHONPATH=. pytest tests`. `tests/test_opta_v3.py` covers the v3 contract (new types/qualifiers, stoppage-time clock, new stats) with small synthetic inputs. Set `ETL_TEST_HISTORY_DATABASE_URL` and `ETL_TEST_STATS_DATABASE_URL` to disposable PostgreSQL databases to include persistence/restart tests. Unit tests use repository doubles; they do not claim database coverage. Docker builds use `--target runtime` for the service and `--target test` for pytest; the runtime excludes tests and test dependencies.

**Inspect:** history DB views `raw_recording_events` (unaltered source JSON), `raw_event_history` (observed canonical deliveries); stats DB view `standard_stats` (per snapshot/team/metric). Full recordings are stored once. History deliveries are stored once per run; snapshots retain watermarks, not duplicate event arrays.

**Publication:** history commits first, then the separately stored projection. No success is returned until both exist. A failed second write is repaired by retrying the same immutable snapshot; reads fail closed while incomplete. The demo recomputes small match projections during ingestion, never on standard-stat reads. It is not a distributed stream-processing implementation.

**Brokers:** set both `MATCH_EVENTHUB_CONNECTION_STRING` and `SNAPSHOT_SERVICEBUS_CONNECTION_STRING`. Names default to `MATCH_EVENTHUB_NAME=match-events` and `SNAPSHOT_SERVICEBUS_TOPIC=match-notifications`. Provision the Event Hubs consumer group `etl`. Broker mode rejects HTTP snapshot writes with 409; recording, snapshot and GraphQL reads stay available. Without these settings, HTTP publication remains an isolated fixture mode.

One consumer receives version-1 `MatchEvent` messages and validates each event against the owned recording. The stub materialises the prefix to recover missed/replayed deliveries, commits both stores, publishes `MatchSnapshotReady`, then checkpoints. Transient database/broker failures retry the same delivery; invalid/conflicting messages are logged without payloads and skipped. Checkpoints are memory-only: restarting replays retained Event Hubs messages, so consumers must tolerate duplicate notifications. This is a local recovery strategy, not production checkpoint durability. `/health` reports the transport and whether its receiver task is running, not network readiness.

**Production:** Azure SQL history, Cosmos stat state, durable checkpoints and Stream Analytics aggregation remain planned. Preserve revision/tombstone handling and readable-state-before-notification. The Azure SDK transports now run against the real emulators; recording-prefix materialisation is still a demo substitute. No cloud apply or scheduled automation is part of this setup.
