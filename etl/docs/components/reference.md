# Reference

> **In short:** the ETL's rules written again in plain Python: Opta codes, key-event detection, per-minute deltas, notifications, the running-totals view, the MA3 → SPADL conversion, the stat catalogue and the trend indicators. Stream Analytics cannot run locally, so this is the expected result that tests, the local loader and the Azure verifier compare against.

| | |
| --- | --- |
| **Status** | Implemented · tested |
| **Code** | [`reference/`](../../reference/): `opta.py`, `pipeline.py`, `spadl.py`, `catalogue.py`, `trends.py` |
| **Used by** | [seeder](seeder.md), [devtools](devtools.md) (`load-local`, `verify`, `check-notifications`), the [SPADL post-processor](spadl.md) (`spadl.py` at runtime), tests |
| **Mirrors** | [Stream Analytics](stream-analytics.md) query, [SQL](sql.md) view and `statsAtSeq` |

## 1. `opta.py`

*In short: codes and single-event rules.*

| Function / constant | Purpose |
| --- | --- |
| Codes (from `contracts/opta-codes.json`) | Event types and qualifiers by name |
| `has_q`, `q_value` | Qualifier lookups (as the UDFs) |
| `qualifiers(row)` | `{qualifierId: value}` of an MA3 row (catalogue and trends) |
| `key_event(event)` | `(keyType, detail)` or `None` |
| `period_change(event)` | `PeriodStarted` / `PeriodEnded` or `None` |
| `stat_deltas(event)` | The event's contribution to each minute statistic |
| `minute_label(period, timeMin)` | Broadcast label, e.g. `45+2'` |

## 2. `pipeline.py`

*In short: a whole replay in, every table row and notification out.*

| Function | Produces |
| --- | --- |
| `kind(message)` | `MA1`, `MA3`, `POS` (by `feed`) or `MatchEvent` (v2, no `feed`); else `None` |
| `stream_outputs(messages, window)` | The rows for every table (`pipeline.TABLES`) and every notification the job should emit, using the same windows |
| `progress_marks(messages)` | The job's `matchProgressMarks` rows (send order) |
| `watermark(marks, rows, matchId)`, `match_status(match, events, seq)` | What Azure SQL's triggers and the local worker make of them: `matchProgress.seq` and `matches.status` |
| `notification_body`, `message_id_for` | Exact Service Bus bodies and `MessageId`s |
| `stats_as_of(minute_rows, matches)` | What `matchStatsAsOf` should return, including `possessionPct` |

## 3. `spadl.py`

*In short: MA3 rows → SPADL actions, whole match or live prefix; runs in production.*

A pure-Python port of socceraction 1.5.3's Opta rules (MIT; [notice](../../reference/THIRD-PARTY-NOTICES.txt)), no pandas. `actions(rows, home)` converts a whole match; `final_actions(rows, home, first_action_id)` returns the actions a live prefix has finalised (`finalSeq`), which the [post-processor](spadl.md) stores; `zone()` gives team-relative zones. Tests compare every recording with socceraction itself (exact, empty allow-list) and incremental with whole-match conversion. The module docstring lists its deliberate differences; none changes a recording.

## 4. `catalogue.py`

*In short: `statsAtSeq` in Python.*

`definitions()` reads the `statDefinitions` seed from `sql/migrations/008_spadl_catalogue.sql` (one source of configuration). `stats_at_seq(match, teams, events, samples, seq, watermark, actions=…, raw=…)` returns the procedure's (`009`) rows from SPADL actions, MA3 card and VAR rows and POS samples; tests check it against the recorded golden values and the SQL procedure.

## 5. `trends.py`

*In short: the trend procedures in Python.*

`definitions()` reads the newest `@trendDefinitions` seed block in `sql/migrations`. `minute_rows`, `trend_minutes_at_seq`, `trends_at_seq` and `spells_at_seq` take the same rows as `stats_at_seq` (`match, events, samples, seq, watermark, defs, actions=…, raw=…`) and return the procedures' rows ([trends](trends.md)); tests compare them with SQL Server on every recording.

When a rule changes, change the query and this module together; the tests and `verify` will show any difference.
