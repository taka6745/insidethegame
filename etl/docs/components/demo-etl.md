# Demo ETL (stand-in)

> **In short:** a replaceable stand-in for the Azure pipeline, used by the shared local Docker stack (`./dev up backend`). It replays the recorded Chelsea–United GRF match from Event Hubs into two PostgreSQL databases (history and standard stats), serves them over a Python GraphQL API and announces each readable snapshot on Service Bus as `MatchSnapshotReady`. The Azure pipeline lives in the other folders of `etl/`.

| | |
| --- | --- |
| **Status** | Implemented · tested · runs in the local Docker stack (not deployed) |
| **Code** | [`demo_etl/`](../../demo_etl/) (layered: `models/`, `services/`, `repositories/`, `adapters/`, `routes/`) |
| **Image** | [`Dockerfile`](../../Dockerfile) (`runtime` and `test` targets), built by [`local/compose.yaml`](../../../local/compose.yaml) as service `etl` |
| **Storage** | PostgreSQL databases `etl_history` and `etl_stats` |
| **Tests** | `test_etl.py`, `test_brokers.py`, `test_native_events.py` (Postgres tests skip without `ETL_TEST_*_DATABASE_URL`) |
| **Contract** | [demo-api.md](../demo-api.md): HTTP routes, GraphQL `questionData`, `MatchEvent` in, `MatchSnapshotReady` out |

```text
Replay → Event Hubs → ETL demo → history + statistics → GraphQL
                              → Service Bus snapshot-ready notification
```

## 1. Structure

*In short: routes call a service; repositories own connections; one adapter owns provider keys.*

The runnable adapter lives in `demo_etl/`. HTTP routes call `MatchService`; repositories own connections; `RecordingSource` owns provider keys. Keep the future Azure implementation separate and preserve these read contracts.

## 2. Running and testing

*In short: uvicorn from this folder, or the shared Docker stack; tests with or without real PostgreSQL.*

**Run:** `uvicorn demo_etl.app:from_env --factory --port 8000` from this folder. Set `ETL_HISTORY_DATABASE_URL`, `ETL_STATS_DATABASE_URL` to two local PostgreSQL databases and `DEMO_RECORDING_PATH` to the generated recording. Docker uses the same entry point. See root development commands for the integrated stack.

**Test:** install `requirements-test.txt`, then `PYTHONPATH=. pytest tests`. Set `ETL_TEST_HISTORY_DATABASE_URL` and `ETL_TEST_STATS_DATABASE_URL` to disposable PostgreSQL databases to include persistence/restart tests. Unit tests use repository doubles; they do not claim database coverage. Docker builds use `--target runtime` for the service and `--target test` for pytest; the runtime excludes tests and test dependencies.

## 3. Data and publication

*In short: history commits first, then the stat projection; reads fail closed until both exist.*

**Inspect:** history DB views `raw_recording_events` (unaltered source JSON), `raw_event_history` (observed canonical deliveries); stats DB view `standard_stats` (per snapshot/team/metric). Full recordings are stored once. History deliveries are stored once per run; snapshots retain watermarks, not duplicate event arrays.

**Publication:** history commits first, then the separately stored projection. No success is returned until both exist. A failed second write is repaired by retrying the same immutable snapshot; reads fail closed while incomplete. The demo recomputes small match projections during ingestion, never on standard-stat reads. It is not a distributed stream-processing implementation.

## 4. Broker mode

*In short: consumes `MatchEvent` from Event Hubs, publishes `MatchSnapshotReady` on Service Bus.*

set both `MATCH_EVENTHUB_CONNECTION_STRING` and `SNAPSHOT_SERVICEBUS_CONNECTION_STRING`. Names default to `MATCH_EVENTHUB_NAME=match-events` and `SNAPSHOT_SERVICEBUS_TOPIC=match-notifications`. Provision the Event Hubs consumer group `etl`. Broker mode rejects HTTP snapshot writes with 409; recording, snapshot and GraphQL reads stay available. Without these settings, HTTP publication remains an isolated fixture mode.

One consumer receives version-1 `MatchEvent` messages and validates each event against the owned recording. The stub materialises the prefix to recover missed/replayed deliveries, commits both stores, publishes `MatchSnapshotReady`, then checkpoints. Transient database/broker failures retry the same delivery; invalid/conflicting messages are logged without payloads and skipped. Checkpoints are memory-only: restarting replays retained Event Hubs messages, so consumers must tolerate duplicate notifications. This is a local recovery strategy, not production checkpoint durability. `/health` reports the transport and whether its receiver task is running, not network readiness.

## 5. Relationship to the Azure pipeline

*In short: the Azure pipeline is built and deployed; the stand-in's contract is what the local stack uses today.*

When the stand-in was written, Azure SQL history, Cosmos stat state, durable checkpoints and Stream Analytics aggregation were planned. Preserve revision/tombstone handling and readable-state-before-notification. The Azure SDK transports now run against the real emulators; recording-prefix materialisation is still a demo substitute. No cloud apply or scheduled automation is part of this setup.

The Azure pipeline in this folder (`stream-analytics/`, `sql/`, `dab/`, `infra/`) now implements Azure SQL history, Stream Analytics aggregation and the Service Bus notifications, with its own contract: per-minute `MinuteClosed`, `KeyEventDetected` and period notifications, and stats from the `matchStatsAsOf` view in Azure SQL rather than Cosmos DB. See [decisions.md](../decisions.md#3-open-items) for the open reconciliation item.
