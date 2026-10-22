# Match data

> **In short:** everything the engine reads from the ETL, behind one interface. `etl_graphql.py` queries the ETL's Data API builder in Azure or locally; the test double `devtools/fixture_data.py` serves a replay file from memory for tests and offline runs. Every read is bounded by a match clock, or by the canonical seq of the latest MA3 row up to it, and MA3 reads also by the ETL's committed seq (`eventSeq ≤ matchWatermarks.seq`), so the engine never sees events the ETL has not announced or committed.

| | |
| --- | --- |
| **Status** | Implemented · tested against a fake DAB and read-only against the Azure dev DAB |
| **Code** | [`narrative_engine/match_data/`](../../narrative_engine/match_data/): `__init__.py` (interface), `etl_graphql.py`; test double in [`devtools/fixture_data.py`](../../narrative_engine/devtools/fixture_data.py) |
| **Reads** | ETL GraphQL: `matches`, `rawEvents`, `keyEvents`, `spadlActions`, `matchWatermarks.spadlSeq`, `executeStatsAtSeq`, `executeTrendsAtSeq`, `executeTrendSpellsAtSeq` ([ETL contracts](../../../etl/contracts/README.md), [local contracts §3–4](../../../local/contracts.md#3-etl-graphql-dab)) |
| **Tests** | `test_graphql_data.py`, `test_recording_run.py`, `test_graphql_live.py` (skips when the ETL is unreachable) |

## 1. Interface (`MatchData`)

*In short: bounded reads, by clock and committed seq (MA3), clock (key events) or seq (SPADL actions, catalogue stats).*

| Method | Returns |
| --- | --- |
| `match_info(matchId)` | Teams, home/away, names, final period (`capabilities.periods`) and MA1 `timeStamp` (from the MA1 payload) |
| `events(matchId, start, end, until_sec)` | MA3 events from `start` to `end`, the last minute only up to `until_sec`, with `eventSeq ≤ matchWatermarks.seq`; `EtlBehind` while the range holds rows past it |
| `actions(matchId, afterSeq, seq)` | `spadlActions` with `afterSeq < finalSeq ≤ seq`, by `actionId`: the SPADL actions settled in that span |
| `stats_at(matchId, seq)` | `executeStatsAtSeq` rows: the SPADL stat catalogue (126 ids) at `seq`; `[]` for no seq |
| `trends_at(matchId, seq)` | `executeTrendsAtSeq` rows at `seq`, enabled trends only, as `indicator contestantId window minutes value previous delta level trend` (served `trendId`, `baseline`, `change`); `[]` means behind (retried, then `EtlBehind`) |
| `spells_at(matchId, seq)` | `executeTrendSpellsAtSeq` rows at `seq`, enabled kinds only (`[]` is an answer) |
| `key_events(matchId, until, until_sec)` | The key-event ledger up to a clock and second |
| `period_end(matchId, periodId)` | Where a period ended, or `None` if not yet written or committed |
| `raw_event(matchId, contestantId, eventId)` | The event a VAR overturn refers to |
| `event_seq(matchId, until, until_sec)` | MA3 `eventSeq` of the latest `rawEvents` row (by `seq`) up to a clock and second, committed rows only (`EtlBehind` as `events`); `None` if none |
| `event_seq_of(matchId, id)` | MA3 `eventSeq` of one row (a key event's `id`): a key-event step's seq and the narrative's `eventSeq` |

## 2. ETL GraphQL client (`etl_graphql.py`)

*In short: DAB filters as GraphQL variables, with retries for cold starts.*

- Clock bounds compare `(periodId, timeMin, timeSec)` in order, because `timeMin` repeats across periods.
- Requests retry with backoff (0.5 s doubling). DAB scales to zero and SQL auto-pauses, so the first request of a match can take about 30 s.
- SPADL and trend reads wait for `matchWatermarks.spadlSeq ≥ seq` (the post-processor trails the MA3 write by about a poll), so they never see a partial conversion; `executeStatsAtSeq` answering `[]` is retried too. Still behind after the retries: `EtlBehind`, and the orchestrator pauses and retries the work.
- Only final actions are stored, so the window `(afterSeq, seq]` is the same however late it is read: backlog equals live (`test_recording_run.py`).
- Pages are followed until complete.

## 3. Fixture reader (`devtools/fixture_data.py`)

*In short: the same interface over a replay file and its notifications; a test double, never used by the service.*

`FixtureMatchData` loads an ETL replay, its notifications (or key-event rows) and its SPADL actions, and answers the same queries in memory; stats come from a `{seq: rows}` table.

| Replay | SPADL actions | Used by |
| --- | --- | --- |
| `tests/fixtures/itg-syn-0001.jsonl` (synthetic seeder match; no canonical seqs, so MA3 `seq` stands in for `eventSeq`) | `tests/fixtures/itg-syn-0001-spadl.json`, written by `tools/spadl_fixture.py` with the ETL's converter | orchestrator, GraphQL and service tests |
| Chelsea–United recording (`data-generation/recordings/`) | the ETL's `etl/tests/fixtures/spadl-chelsea-united.json`; golden stats `catalogue-golden.json` | render snapshots, whole-match backlog-vs-live run |

A full fake-agent run over the GraphQL client against a fake DAB gives the same prompts as the fixture run.
