# Backend tests

Run **`ACCEPT_EULA=Y ./dev up backend`**, then **`./dev test backend`** after changes. No model or cloud account required.

| Check | Evidence |
| --- | --- |
| Foundation profiles / buckets | All 12 combinations return matching history and three legacy-harness cards |
| Product viewer | Five ETL-backed cards; custom tracking replaces the lowest-priority default and untracking restores it |
| Pins | Lowest-priority default replaced; unpin restores current default; full custom cards require explicit replacement |
| Persistence / concurrency | Real Postgres, isolated schema per test; concurrent pins and reconnect preserve state |
| Sessions | New session revokes HTTP token and closes old socket; one socket per token |
| Live updates | One shared upstream read per relevant bucket; individual pin order; failed delivery retry, bounded receipts and slow-socket cleanup |
| Data integrity | Duplicate/conflicting events, wrong match, VAR cancellation, invalid/stale stat selections |
| Coding workflow | Missing data rejected before generation; wrong results/errors repaired; stop after initial attempt + three repairs |
| ETL ownership | Standard values pass through unchanged; no raw-history query or standard recalculation, even when a custom pin is active |
| Running stack | Recorded events → Event Hubs → ETL history/stats → Service Bus narratives; GraphQL snapshots at start, duplicate first event, minute 1, just after half-time and full time |
| Structured filters | 26 scenario presets, time boundaries, membership/ranges, count/sum, corrections and retractions |
| Shared index | 100,000 distinct rules; fixed probe bound and relevant candidate counts; equivalent-rule reuse |
| Filter lab | Real Postgres registration, late backfill, versions, restart, reset and API validation |
| Local-model workflow | Goal/coder contracts, semantic constraints, sample-event checks, repair limits, timeouts and fixture mode |
| Data reference | Generated types, missing-definition rejection, profile substitution, isolated request context and independent transfer-oracle mutation checks |
| Question agent | Intent routing before numeric context, snapshot-bound reads, selected one-off offers, clarification, bounded admission, persistence and reset/takeover races |
| Narrative transport | Real Service Bus delivery into a durable inbox; unchanged bucket text; acknowledgement/dead-letter/retry unit checks |

`tests/` runs domain checks plus real-Postgres tests in isolated schemas. `./dev test backend` then runs two real AMQP checks: `local/broker_check.py` verifies Event Hubs delivery, ETL GraphQL history/stats and Service Bus narratives at start, duplicate first event, minute 1, just after half-time and full time; `local/backend_broker_check.py` verifies the backend custom index, duplicate handling, database restore, durable narrative inbox and disabled HTTP checkpoint writes. These use separate runs, consumer groups/subscriptions and an isolated backend schema, then restore the active viewer watermark without resetting its replay or sessions. They do not test browser playback or cloud deployment.

The older `backend/smoke.py` and `backend/lab_smoke.py` remain fixture-only tools, excluded from `./dev test backend`. They assume their old synthetic scenarios and can reset shared state; do not point them at the GRF demonstration. Upstream service tests run separately: [ETL](../../etl/docs/development.md) and [narrative](../../narrative-engine/docs/development.md).

The older coding harness uses scripted executor doubles. The new filter lab actually evaluates typed rules against canonical events, including time edges and headed passes versus headed shots. Unit tests mock model responses and check all fixture goals; live local-model verification is separate and is not required for `./dev test backend`. No generated Python executes, and a few successful live requests do not establish general model accuracy.

`test_narrative_transport.py` retains coverage of the older standalone Service Bus adapter. `test_product_brokers.py` covers the product broker contracts and persistence/retry boundaries; the two integration scripts exercise actual emulator delivery. `./dev test azure` separately checks the foundational emulator protocols.

Not established by this suite: production Event Hubs ingestion and Service Bus deployment, production GraphQL snapshot contracts, end-to-end lost-message recovery, broker history/live handoff, general model accuracy, generated-code isolation, authentication, load capacity, multiple API replicas or cloud deployment. See [question readiness](question-readiness.md) for demonstration and submission boundaries.

Frontend tests: `cd frontend && npm test` (Node required only for these small JavaScript unit tests). The Docker UI itself requires no host Node installation.
