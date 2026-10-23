# Decisions

> **In short:** the design planned a replay of an existing synthetic match into Event Hubs. We built a renderer for new fictional-league matches and a feed service that behaves like an external provider, with several concurrent runs.

| | |
| --- | --- |
| **Design** | [design/original-design.md](design/original-design.md) |
| **Plan** | Multi-match plan ([local contracts](../../local/contracts/README.md)) |

## 1. Kept from the design

*In short: GRF in, Event Hubs out, synthetic labels and provenance throughout.*

- Source is Google Research Football; every message carries `synthetic: true` and MA1 carries provenance and the recording's SHA-256.
- Event Hubs `match-events` is the only data path to ETL and the backend.

## 2. Added or changed

*In short: each change answers a gap the design left open.*

| Design | Built | Why |
| --- | --- | --- |
| Replay an existing match | Real-time rendered matches with aligned video | Events and footage must agree to the second |
| Replay tool, hosting undecided | Feed service (own DB, own container) | Behaves like an external provider; nothing else mounts recordings or media |
| One match | N runs at once, `matchId = {fixture}-{run8}` | Concurrent demos; every run isolated and purgeable |
| — | Opta-style events, F24 and MA1/MA3/POS exports | A widely known format for ETL |
| — | Played-only HLS; no seek on the demo path | Future data is physically unreachable |
| — | Purge with permanent tombstones | Purged matches never come back |
| — | Start demo: exactly three fixtures, main game first, one demo at a time, run cap `409` | Every viewer gets the same three live matches however many click |
| — | Seeded starts: held runs record, waiting runs resume after restore (`DEMO_SEEDS` only) | Mid-match starts with a real story so far, never reconstructed and never past the point |
| Equal built-in AIs | Scripted per-fixture team tactics ([grf-demo §4](components/grf-demo.md#4-scripted-tactics)) | Unscripted GRF minutes behave as independent draws: no spells, momentum or game state for storylines |

## 3. Open items

*In short: what remains.*

- Fixture metadata (names, codes, colours, crests, players) lives in `grf_demo/league.json` and kit colours in `roster.py` `_KIT`; a new fixture needs entries there as well as a recording.
- MA3 timestamps follow the ETL window rule, so second-half rows are stamped up to a minute after they are sent.
- Seeds are recorded per build; a schema change on any owner means recording them again.
