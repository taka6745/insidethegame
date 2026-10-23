# Demo

> **In short:** a demo-only ASGI layer, mounted only with `DEMO_SEEDS=1`, that exports one match's documents and restores them under a new matchId, so a demo can start mid-match. A production release (`./dev azure up --release`) has no seed routes.

| | |
| --- | --- |
| **Status** | Implemented · tested (`test_servicebus.py`: export → purge-all → restore under a new id → continue; no seed routes without `DEMO_SEEDS`) |
| **Code** | [`narrative_engine/demo/seeds.py`](../../narrative_engine/demo/seeds.py) (`seed_app` wraps the service app in `service.py`) |
| **Routes** | `POST /admin/matches/export {match_id}` → `{match_id, schema, containers}`; `POST /admin/matches/restore {match_id, max_seq, schema, containers}` → `{match_id, restored}`; bearer `ADMIN_TOKEN` when set |
| **Seeded** | `checkpoints` (follow state and pending follow steps cleared), `contextBlocks`, `narratives`, `analyses`, `storylines`; never viewers' follow decisions or follow narratives |
| **Caller** | [Demo control](../../../local/docs/components/demo-control.md), never the viewer |
| **Helpers** | Bearer check, JSON responses and body reading shared with the service app (`transport/asgi.py`) |

## 1. Restore

*In short: restored documents look as if the engine had run since kick-off.*

Restore writes documents in the shapes the orchestrator writes, then registers the match (`Router.engine`) as after a restart, so the next notification continues from the seed; no core code branches on a demo. It answers `409` for another schema fingerprint, a known, purged or tombstoned match, documents of another match, or narratives past `max_seq`; `422` for a malformed body; `503` for any other failure (demo control then purges the run everywhere). Without `DEMO_SEEDS=1` neither route exists (`test_without_the_demo_setting_the_service_has_no_seed_routes`).
