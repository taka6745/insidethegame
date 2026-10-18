# Backend tests

Run **`./dev up backend`**, then **`./dev test backend`** after changes. No model or cloud account required.

| Check | Evidence |
| --- | --- |
| Profiles / buckets | All 12 combinations return matching history and three cards |
| Pins | Lowest-priority default replaced; unpin restores current default; full custom cards require explicit replacement |
| Persistence / concurrency | Real Postgres, isolated schema per test; concurrent pins and reconnect preserve state |
| Sessions | New session revokes HTTP token and closes old socket; one socket per token |
| Live updates | Target-bucket narratives, changing stat values and key moments |
| Data integrity | Duplicate/conflicting events, wrong match, VAR cancellation, invalid/stale stat selections |
| Coding workflow | Missing data rejected before generation; wrong results/errors repaired; stop after initial attempt + three repairs |
| ETL ownership | Standard values pass through unchanged; no raw-history query or standard recalculation, even when a custom pin is active |
| Running stack | JSONL → fake services → GraphQL → backend → WebSocket; replay twice; takeover and saved pin |
| Structured filters | 26 scenario presets, time boundaries, membership/ranges, count/sum, corrections and retractions |
| Shared index | 100,000 distinct rules; fixed probe bound and relevant candidate counts; equivalent-rule reuse |
| Filter lab | Real Postgres registration, late backfill, versions, restart, reset and API validation |
| Local-model workflow | Goal/coder contracts, semantic constraints, sample-event checks, repair limits, timeouts and fixture mode |
| Data reference | Generated types, missing-definition rejection, profile substitution, isolated request context and independent transfer-oracle mutation checks |

`tests/` runs domain checks plus real-Postgres tests in isolated schemas. `backend/smoke.py` checks separate Docker services through their network interfaces. `backend/lab_smoke.py` checks the frontend proxy and all 26 presets through 35 deliveries, then resets the lab. These checks modify the synthetic demos; don't run them while someone is using the lab.

The older coding harness uses scripted executor doubles. The new filter lab actually evaluates typed rules against canonical events, including time edges and headed passes versus headed shots. Unit tests mock model responses and check all fixture goals; live local-model verification is separate and is not required for `./dev test backend`. No generated Python executes, and a few successful live requests do not establish general model accuracy.

Not covered yet: real Event Hubs/Service Bus consumers, production GraphQL schemas, lost-message recovery, incremental history/live handoff, model quality, generated-code isolation, auth, load, multiple API replicas or cloud deployment. Existing `./dev test azure` checks emulator protocols independently of this harness.

Frontend tests: `cd frontend && npm test` (Node required only for these small JavaScript unit tests). The Docker UI itself requires no host Node installation.
