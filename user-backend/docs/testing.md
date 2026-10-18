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
| Running stack | JSONL → fake services → GraphQL → backend → WebSocket; replay twice; takeover and saved pin |

`tests/` runs against real Postgres with an in-process fake feed. `backend/smoke.py` then checks the separate running Docker services over their actual network interfaces. It modifies the synthetic match and demo viewer; use `./dev reset backend` for a fresh replay.

The coding test supplies explicit goal cases, including a minute-20 boundary and headed passes that must not count as headed shots. Scripted agent/executor doubles return results: **no generated source is executed**. This proves orchestration, not LLM semantic understanding or sandbox safety.

Not covered yet: real Event Hubs/Service Bus consumers, production GraphQL schemas, lost-message recovery, incremental history/live handoff, model quality, generated-code isolation, auth, load, multiple API replicas or cloud deployment. Existing `./dev test azure` checks emulator protocols independently of this harness.
