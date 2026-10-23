# Checks

> **In short:** each `./dev up`/`./dev test` level runs repeatable checks against the real containers; none touches running matches.

| | |
| --- | --- |
| **Code** | `check.py`, `broker_ready.py`, `etl_stream_check.py`, `broker_check.py`, `backend_broker_check.py` |
| **Shared** | `settings.py` (local endpoints and public emulator credentials); purge owners from `demo_control.OWNERS` |
| **Runs in** | `tools` image (`check.py`), the backend image with `local/` mounted at `/checks` (probes) |

| Script | Run by | Proves |
| --- | --- | --- |
| `check.py base` | `./dev test` | Both Postgres databases read/write (temp tables), Cosmos write/read/delete; creates narrative containers if absent |
| `check.py azure` | `./dev test azure` | Read-only ETL GraphQL (stat catalogue, matches), Event Hubs and Service Bus send/receive on dedicated integration consumers (`IntegrationProbe` messages may reach app consumers; they ignore that type) |
| `broker_ready.py` | Compose `broker-ready` | Both messaging emulators healthy, bounded wait |
| `etl_stream_check.py` | `./dev test backend` | Every ETL GraphQL entity answers; `narrative-live` is readable |
| `broker_check.py` | `./dev test backend` | A synthetic probe match (fresh `broker-check-…` id: MA1, MatchEvent v2 with a duplicate, POS) flows Event Hubs → `etl-stream` → SQL → SPADL → DAB with one stat per enabled kind and scope, the backend lists it, and a purge from every consumer leaves nothing |
| `backend_broker_check.py` | `./dev test backend` | Real Event Hubs → an isolated backend registry and schema: duplicate ignored, PostgreSQL restore agrees |

No cloud throughput or distributed ownership is proved by these checks.
