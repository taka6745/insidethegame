# Filter lab: synthetic event feed

**Hand-authored test data, 18 October 2026.** The fictional Riverton Rovers–Madrid match
and player actions are invented. This is neither collected match data nor an
implementation of a licensed Opta wire schema. Names are illustrative.

`filter-lab.json` contains teams, player IDs, 35 canonical deliveries (including
revisions and a duplicate), and 24 natural-language requests with SPADL rules and
expected final values. Tests turn the deliveries into SPADL actions with the
double in `benchmarks/doubles/spadl.py`: one action per surviving event (its
latest revision, final at that revision's seq); touches and cards have no action
(cards become MA3 card rows). The two card presets were removed on 21 October 2026
(cards are outside SPADL); headed-action and pass counts changed with SPADL.

| Boundary | Contract |
| --- | --- |
| Raw event | `eventId`, `matchId`, `typeName`, `teamId`, `playerId`, `periodId`, `timeMin`, `timeSec`, `outcome`, named `qualifiers` |
| Adapter | `backend/adapters/events.py` maps this fixture into immutable canonical events |
| SPADL double | `benchmarks/doubles/spadl.py`: `corner` → `corner_crossed`, `goal` → `shot` success, `save` → `keeper_save`, … |
| Rule | AND SPADL predicates; `eq`, `in`, `gt`, `gte`, `lt`, `lte`; count or sum of start → end distance |
| Time | Whole-match football clock; second half starts at minute 45. Use `period` for halves because stoppage time overlaps |
| Correction | Same event ID, higher `revision`, full replacement; `deleted: true` retracts it |

## Meaning matters

- A fixture `corner` becomes a taken corner (`corner_crossed`), a pass-family
  action, so SPADL pass counts include corners.
- “Headers” means head-tagged SPADL actions (passes, clearances, shots); touches
  have no SPADL action. It is not a count of aerial challenges won.
- A goal is a shot-family action with result `success`; shot attempts are the
  shot family.
- The double sets each pass's end `distanceMetres` ahead of its start, so the
  start → end distance equals the supplied measurement.
- Revision and deletion syntax, named qualifiers and outcomes are our test
  contract. There are no assumed official vendor numeric IDs.

## Research and provenance

Primary source checked 18 October 2026:
[Stats Perform’s Opta Event Definitions](https://www.statsperform.com/opta-event-definitions/).
It distinguishes headed passes, body-part attribution for attempts, corners
awarded versus taken, and amendments/deletions after VAR decisions. Those
semantic distinctions informed these invented cases. Public definitions do not
establish a complete delivery schema; a real feed requires its agreed contract
and a separate adapter. No vendor event samples were copied.

## Execution limits

The index references rules by equality/membership combinations; event processing
probes at most 64 keys before evaluating candidates.
Range-only and otherwise broad rules remain real work. This is a bounded lookup
algorithm, not proof of production throughput for 100 million viewers. Rules,
events and state remain in memory inside the pure engine; its application
service owns persistence and serialized access.
