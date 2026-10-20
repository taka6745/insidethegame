# Filter lab: synthetic event feed

**Hand-authored test data, 18 October 2026.** The fictional Chelsea–Madrid match
and player actions are invented. This is neither collected match data nor an
implementation of a licensed Opta wire schema. Names are illustrative.

`filter-lab.json` contains teams, player IDs, 35 deliveries (including revisions
and a duplicate), and 26 natural-language requests with structured rules and
independently specified expected final values. The frontend can use these as a
removable event source. Replay uses array order, including corrections.

| Boundary | Contract |
| --- | --- |
| Raw event | `eventId`, `matchId`, `typeName`, `teamId`, `playerId`, `periodId`, `timeMin`, `timeSec`, `outcome`, named `qualifiers` |
| Adapter | `backend/adapters/events.py` maps this fixture into immutable canonical events |
| Rule | AND predicates; `eq`, `in`, `gt`, `gte`, `lt`, `lte`; count or sum of supplied distance |
| Time | Whole-match football clock; second half starts at minute 45. Use `period` for halves because stoppage time overlaps |
| Correction | Same event ID, higher `revision`, full replacement; `deleted: true` retracts it |

## Meaning matters

- A fixture `corner` means **awarded**, not taken. These totals can differ.
- “Headers” here means recorded head-tagged ball actions, including passes,
  clearances, shots and touches. It is not a count of aerial challenges won.
- Goal events replace shot events in this fixture. A shot-attempt rule must use
  `event_type in ["shot", "goal"]` to include scored attempts.
- `distanceMetres` is a supplied synthetic measurement, not distance derived by
  the user backend from coordinates. Missing measurements contribute zero to a
  sum; no missing distance is inferred.
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
probes at most 64 keys (128 for corrections) before evaluating candidates.
Range-only and otherwise broad rules remain real work. This is a bounded lookup
algorithm, not proof of production throughput for 100 million viewers. Rules,
events and state remain in memory inside the pure engine; its application
service owns persistence and serialized access.
