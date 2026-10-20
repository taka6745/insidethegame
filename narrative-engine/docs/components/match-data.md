# Match data

> **In short:** everything the engine reads from the ETL, behind one interface. `etl_graphql.py` queries the ETL's Data API builder in Azure or locally; `fixture.py` serves a replay file from memory for tests and offline runs. Every read is bounded by a match clock so the engine never sees events the ETL has not announced.

| | |
| --- | --- |
| **Status** | Implemented · tested against a fake DAB and read-only against the Azure dev DAB |
| **Code** | [`narrative_engine/match_data/`](../../narrative_engine/match_data/): `fixture.py` (interface + fixture reader), `etl_graphql.py` |
| **Reads** | ETL GraphQL: `matches`, `rawEvents`, `keyEvents`, `matchStatsAsOfs` ([ETL contracts](../../../etl/contracts/README.md)) |
| **Tests** | `test_graphql_data.py`, `test_graphql_live.py` (skips when the ETL is unreachable) |

## 1. Interface (`MatchData`)

*In short: six bounded reads.*

| Method | Returns |
| --- | --- |
| `match_info(matchId)` | Teams, home/away, names (from the MA1 payload) |
| `events(matchId, start, end, until_sec)` | MA3 events from `start` to `end`, the last minute only up to `until_sec` |
| `stats_as_of(matchId, clock, expect_row)` | Home and away running totals at the latest minute at or before `clock` |
| `key_events(matchId, until, until_sec)` | The key-event ledger up to a clock and second |
| `period_end(matchId, periodId)` | Where a period ended, or `None` if not yet written |
| `raw_event(matchId, contestantId, eventId)` | The event a VAR overturn refers to |

## 2. ETL GraphQL client (`etl_graphql.py`)

*In short: DAB filters as GraphQL variables, with retries for cold starts.*

- Clock bounds compare `(periodId, timeMin, timeSec)` in order, because `timeMin` repeats across periods.
- Requests retry with backoff (0.5 s doubling). DAB scales to zero and SQL auto-pauses, so the first request of a match can take about 30 s.
- `stats_as_of(…, expect_row=True)` retries briefly when the minute had events but its statistics row is not visible yet (the ETL writes SQL and sends `MinuteClosed` together).
- Pages are followed until complete.

## 3. Fixture reader (`fixture.py`)

*In short: the same interface over a replay file and its notifications.*

`FixtureMatchData` loads an ETL replay (`tests/fixtures/itg-syn-0001.jsonl`, synthetic) and the notifications the ETL reference pipeline produced for it, and answers the same queries in memory. A full fake-agent run over the fixture gives the same narratives as a run against the Azure dev DAB, which is how the GraphQL client is checked.
