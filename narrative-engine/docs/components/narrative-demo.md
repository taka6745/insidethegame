# Narrative demo (stand-in)

> **In short:** a replaceable stand-in for the engine, used by the shared local Docker stack (`./dev up backend`). It serves 144 manually authored narratives for the recorded Chelsea–United GRF match and factual recap history, over the same Service Bus and GraphQL boundary the user backend uses. It never calls a model. The real engine lives in `narrative_engine/`.

| | |
| --- | --- |
| **Status** | Implemented · tested · runs in the local Docker stack (not deployed) |
| **Code** | [`narrative_demo/`](../../narrative_demo/) (layered: `models/`, `services/`, `repositories/`, `adapters/`, `routes/`), [`fixtures/`](../../fixtures/README.md), [`tools/bind_commentary.py`](../../tools/bind_commentary.py), [`prototypes/bucket_framing/`](../../prototypes/bucket_framing/README.md) |
| **Image** | [`demo.Dockerfile`](../../demo.Dockerfile), built by [`local/compose.yaml`](../../../local/compose.yaml) as service `narrative` |
| **Storage** | Single-process SQLite archive |
| **Tests** | `test_narrative_demo.py`, `test_brokers.py`, `test_recorded_commentary.py` |
| **Contracts** | Input `MatchSnapshotReady` (ETL demo), audience `generation_targets` ([audience API](../../../user-backend/docs/audience-api.md)), output `BucketNarratives` |

## 1. Running it

*In short: from this folder with uvicorn, or as part of the shared Docker stack.*

```sh
cd narrative-engine
pip install -r requirements-dev.txt
python -m pytest
ETL_BASE_URL=http://localhost:18001 \
AUDIENCE_BASE_URL=http://localhost:18000 \
NARRATIVE_DATABASE_PATH=../.local/narrative-demo.sqlite3 \
NARRATIVE_FIXTURE_PATH=fixtures/grf-narratives.json \
uvicorn narrative_demo.app:from_env --factory --port 18030
```

| Setting | Purpose |
| --- | --- |
| `ETL_BASE_URL` | Read-only access to ETL's captured checkpoints |
| `AUDIENCE_BASE_URL` | Backend's read-only audience catalogue |
| `NARRATIVE_DATABASE_PATH` | Demo SQLite archive; preserve its volume across restart |
| `NARRATIVE_FIXTURE_PATH` | Authored commentary bound to the exact recording hash |

## 2. HTTP fixture mode and GraphQL

*In short: isolated tests post checkpoints over HTTP; GraphQL serves the backend's `questionData` contract.*

In isolated HTTP fixture mode, `POST /demo/viewer-snapshots` accepts checkpoint metadata with `events: []`. ETL must already own that checkpoint. This service retrieves `GET /demo/snapshots/{id}` from ETL, validates the observed delivery hash and watermark, archives neutral recaps, and selects authored narratives for current `generation_targets`. Empty targets publishes nothing; a catalogue error fails explicitly rather than silently enabling everyone. Same-cursor audience changes can reread existing authored versions.

`POST /demo/question-snapshots` materializes neutral context from that same ETL checkpoint if needed. It never fetches audience configuration or authors/publishes bucket narratives. This allows a question to race the viewer update safely.

`POST /graphql` exposes the existing bounded `questionData(snapshotId, operation, …)` contract:

- `viewer`: observed, enabled bucket narratives and recent canonical events.
- `compact`: a nonoverlapping frontier of neutral context, unfinished-minute events and key-event ledger.
- `recaps`: retained blocks filtered by IDs, tier or interval, in pages of at most 100.

Minute, five-minute, ten-minute, twenty-minute and half-time blocks remain readable after compaction. Only completed intervals exist. A full 90-minute checkpoint uses two half blocks; the archived children remain available for deeper questions. Football clock is separate from the accelerated recording's video time.

## 3. Broker mode

*In short: consumes `MatchSnapshotReady`, publishes one bounded `BucketNarratives` document per checkpoint.*

Set `SNAPSHOT_SERVICEBUS_CONNECTION_STRING` to enable the lifespan-managed consumer. Set `NARRATIVE_SERVICEBUS_CONNECTION_STRING` for its publisher, or omit it to reuse the input connection. Connection strings belong in ignored local configuration.

| Setting | Default |
| --- | --- |
| `SNAPSHOT_SERVICEBUS_TOPIC` | `match-notifications` |
| `SNAPSHOT_SERVICEBUS_SUBSCRIPTION` | `narrative-engine` |
| `NARRATIVE_SERVICEBUS_TOPIC` | `narratives` |

Input: `{type: "MatchSnapshotReady", version: 1, snapshot: <SnapshotInput metadata>}`. The nested metadata contains `events: []`; ETL must have committed the referenced snapshot before publishing. Output: `{type: "BucketNarratives", version: 1, snapshot: <checkpoint watermark>, items, events, audience_revision}`. Items are already bucket-framed and remain unchanged in the backend. The output is a bounded current document (up to 480 narratives and 30 recent events), not a per-viewer message.

The service archives before sending and acknowledges input only after publishing succeeds. Invalid JSON/contracts dead-letter. Transient ETL, audience, storage or publishing failures retry in place with exponential backoff capped at 15 seconds; automatic lock renewal runs for up to five minutes. Cancellation propagates without acknowledging unfinished work. If the lock expires, the receiver reconnects for broker redelivery. An outage exceeding repeated renewal windows can still exhaust the broker delivery limit; inspect the dead-letter queue and republish the current checkpoint after recovery. This stub has no separate durable retry scheduler. Integration probes settle without creating commentary. Repeated input notifications republish the current document, allowing a backend startup checkpoint to recover a lost emulator queue. Periodic audience refresh skips unchanged documents. The current metadata and published signature persist in SQLite; a restart resumes audience refresh every two seconds. Regressive same-run `(cursor, period, clock_seconds)` watermarks and older capture times from previous runs cannot replace the active polling snapshot; unseen stale checkpoints are archived as neutral history without live publishing. The backend must additionally reject messages for any inactive run; timestamps are demo ordering metadata, not a production ownership fence.

Both HTTP snapshot POST routes return 409 in broker mode. GraphQL history remains available. Audience changes reselect authored versions for the latest observed checkpoint without a question or an HTTP capture triggering generation. This is at-least-once delivery: a crash after send and before durable signature save can resend, so consumers must be idempotent.

## 4. Commentary fidelity

*In short: authored fixture prose, bound to exact evidence; stale or changed evidence suppresses it.*

`fixtures/grf-narratives.json` is authored fixture data, not a model output. Each item declares its bucket, observed release cursor, clock and exact source events. A different recording hash, future release, deleted evidence or changed evidence suppresses that item. Templates never infer pressure, tactics, possession or player intent from a lone event. The backend displays supplied text unchanged.

The broker path uses Microsoft's real Service Bus SDK and emulator. Archive persistence is still single-process SQLite, not Cosmos. HTTP checkpoint mode is retained only for isolated tests and is disabled when the broker connection is configured. No viewer IDs, account data, provider credentials or per-user model workflows enter this service. Archived backend test doubles may remain isolated in backend tests; they are not its runtime implementation.

The committed [commentary fixture](../../fixtures/README.md) contains 144 manually authored versions (one per bucket per video minute). `tools/bind_commentary.py` binds that prose to an independent ETL canonical export after explicit recording-hash review. It adds no text. Its prefix digest invalidates a narrative if any earlier factual input changes; the last minute additionally requires football clock 5400. Run the fixture tests from the repository checkout so the committed recording is available for the independent evidence check.

## 5. Relationship to the engine

*In short: the engine in `narrative_engine/` is the planned replacement; the two contracts still need reconciling.*

The stand-in's plan was to keep the HTTP/models/services/repository/adapter boundaries, replace authored fixtures with Microsoft Agent Framework summariser, compressor and author agents, and replace SQLite with Cosmos while preserving archive-before-publish ordering. `narrative_engine/` now implements the agents, Cosmos DB and Service Bus parts, against the deployed Azure ETL's contract: per-minute `MinuteClosed` / `KeyEventDetected` notifications in, one message per narrative out, presence for the audience list. The stand-in's contract (`MatchSnapshotReady` in, `BucketNarratives` out, `generation_targets` from the backend) is what the local stack and user backend use today. See [decisions.md](../decisions.md#3-open-items) for the open reconciliation item.
