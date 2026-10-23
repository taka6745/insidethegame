# Fixtures

> **In short:** `fixtures/filter-lab.json` is hand-authored synthetic data for tests and benchmarks: a fictional two-team match (a frozen fixture; its team labels predate the fictional league) with 35 deliveries, corrections and deletions. No real match, player data, footage or Opta content; the runtime never reads it.

| | |
| --- | --- |
| **Code** | [`fixtures/filter-lab.json`](../../fixtures/filter-lab.json) |
| **Used by** | Filter-engine tests, the custom-stat corpus ([benchmarks](benchmarks.md)) through `benchmarks/doubles/spadl.py` |
| **Image** | `test` target only |
| **Status** | Implemented, tested |

## 1. Contents

*In short: teams, players, deliveries and requests with expected values.*

Teams, player ids, 35 canonical deliveries (revisions and a duplicate included) and 24 natural-language requests with SPADL rules and expected final values.

| Boundary | Contract |
| --- | --- |
| Raw event | `eventId`, `matchId`, `typeName`, `teamId`, `playerId`, `periodId`, `timeMin`, `timeSec`, `outcome`, named `qualifiers` |
| Adapter | `benchmarks/doubles/events.py` maps it to immutable canonical events |
| SPADL double | `benchmarks/doubles/spadl.py`: one action per surviving event, final at its last revision's seq; `corner` → `corner_crossed`, `goal` → `shot` success, `save` → `keeper_save`; touches and cards have no action (cards become MA3 card rows) |
| Time | Whole-match clock; the second half starts at minute 45; use `period` for halves |
| Correction | Same event id, higher `revision`, full replacement; `deleted: true` retracts |

## 2. Meaning

*In short: SPADL meanings, not everyday ones.*

- A taken corner is a pass-family action, so pass counts include corners.
- "Headers" are head-tagged actions (passes, clearances, shots), not aerial duels won.
- A goal is a shot-family action with result `success`.
- Each pass's end is set so start → end distance equals the supplied metres.
- Revision syntax, qualifiers and outcomes are this test contract; no vendor numeric ids are assumed.

## 3. Provenance

*In short: informed by public definitions, nothing copied.*

The semantic distinctions (headed passes, body-part attribution, corners awarded versus taken, VAR amendments) follow [Stats Perform's Opta Event Definitions](https://www.statsperform.com/opta-event-definitions/), checked 18 October 2026. Public definitions are not a delivery schema; a real feed needs its agreed contract and its own adapter. No vendor samples were copied.
