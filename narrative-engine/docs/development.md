# Develop shared narratives

![Service boundary](../architecture.svg)

**Own:** neutral memory, bucket narratives and narrative history. ETL owns events/statistics; the backend owns audience definitions. Questions never start narrative authoring.

## Run the replaceable demo

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

`POST /demo/viewer-snapshots` accepts checkpoint metadata with `events: []`. ETL must already own that checkpoint. This service retrieves `GET /demo/snapshots/{id}` from ETL, validates the observed delivery hash and watermark, archives neutral recaps, and selects authored narratives for current `generation_targets`. Empty targets publishes nothing; a catalogue error fails explicitly rather than silently enabling everyone. Same-cursor audience changes can reread existing authored versions.

`POST /demo/question-snapshots` materializes neutral context from that same ETL checkpoint if needed. It never fetches audience configuration or authors/publishes bucket narratives. This allows a question to race the viewer update safely.

`POST /graphql` exposes the existing bounded `questionData(snapshotId, operation, …)` contract:

- `viewer`: observed, enabled bucket narratives and recent canonical events.
- `compact`: a nonoverlapping frontier of neutral context, unfinished-minute events and key-event ledger.
- `recaps`: retained blocks filtered by IDs, tier or interval, in pages of at most 100.

Minute, five-minute, ten-minute, twenty-minute and half-time blocks remain readable after compaction. Only completed intervals exist. A full 90-minute checkpoint uses two half blocks; the archived children remain available for deeper questions. Football clock is separate from the accelerated recording's video time.

## Commentary fidelity

`fixtures/grf-narratives.json` is authored fixture data, not a model output. Each item declares its bucket, observed release cursor, clock and exact source events. A different recording hash, future release, deleted evidence or changed evidence suppresses that item. Templates never infer pressure, tactics, possession or player intent from a lone event. The backend displays supplied text unchanged.

The demo's HTTP checkpoint bridge replaces cloud delivery only for local development. It is a single-process SQLite adapter, not Cosmos or Service Bus emulation. No viewer IDs, account data, provider credentials or per-user model workflows enter this service. Archived backend test doubles may remain isolated in backend tests; they are not its runtime implementation.

## Build next

Keep the HTTP/models/services/repository/adapter boundaries. Replace authored fixtures with Microsoft Agent Framework summariser, compressor and author agents; replace SQLite with Cosmos; persist before publishing Service Bus notifications. The original [prompts](../prompts/README.md) remain unchanged and their text-vs-JSON output conflict still needs resolution. Keep all canonical bucket IDs from the [audience API](../../user-backend/docs/audience-api.md), and read enabled targets before each shared generation cycle.

The committed [commentary fixture](../fixtures/README.md) contains 144 manually authored versions (one per bucket per video minute). `tools/bind_commentary.py` binds that prose to an independent ETL canonical export after explicit recording-hash review. It adds no text. Its prefix digest invalidates a narrative if any earlier factual input changes; the last minute additionally requires football clock 5400. Run the fixture tests from the repository checkout so the committed recording is available for the independent evidence check.
