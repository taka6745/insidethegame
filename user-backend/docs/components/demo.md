# Demo seeds

> **In short:** a demo-only adapter in `backend/demo/` that exports a match's backend rows at a start point and restores them under a new `matchId`, so the viewer's **Start demo** can begin at 20′, half time, 60′ or 85′. Mounted only with `DEMO_SEEDS=1`; core code never branches on a demo.

| | |
| --- | --- |
| **Code** | [`backend/demo/seeds.py`](../../backend/demo/seeds.py) (`SeedRepository`, `demo_seed_router`) |
| **Routes** | `POST /admin/matches/export` `{match_id}`, `POST /admin/matches/restore` `{match_id, max_seq, schema, tables}` (internal; demo control calls them) |
| **Setting** | `DEMO_SEEDS=1` (local compose and the demo build); a production release (`./dev azure up --release`) leaves it off |
| **Tests** | `test_multi_match.py` (round trip), `test_seed_routes_exist_only_with_the_demo_setting` |
| **Status** | Implemented, tested |

## 1. Export and restore

*In short: written as the stream consumer would, then adopted as after a restart.*

Export returns `received_matches`, `received_events`, `match_gaps`, `audience_catalog`, `engine_narratives` and `narrative_clips` for one match. Restore writes them in one transaction, refusing another schema, a known or tombstoned match, rows of another match and rows past `max_seq` (`409 seed_refused`); then `MatchRegistry.adopt` tracks the match as after a restart. Viewers' sessions, follows, questions and calculations are never seeded. Without the setting the routes do not exist. The whole seed flow (record, capture, start) is owned by demo control ([local/contracts/README.md](../../../local/contracts/README.md) §7a).
