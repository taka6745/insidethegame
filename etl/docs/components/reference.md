# Reference

> **In short:** the ETL's rules written again in plain Python: Opta codes, key-event detection, per-minute deltas, notifications and the running-totals view. Stream Analytics cannot run locally, so this is the expected result that tests, the local loader and the Azure verifier compare against.

| | |
| --- | --- |
| **Status** | Implemented · tested |
| **Code** | [`reference/`](../../reference/): `opta.py`, `pipeline.py` |
| **Used by** | [seeder](seeder.md), [devtools](devtools.md) (`load-local`, `verify`, `check-notifications`), tests |
| **Mirrors** | [Stream Analytics](stream-analytics.md) query, [SQL](sql.md) view |

## 1. `opta.py`

*In short: codes and single-event rules.*

| Function / constant | Purpose |
| --- | --- |
| Codes (from `contracts/opta-codes.json`) | Event types and qualifiers by name |
| `has_q`, `q_value` | Qualifier lookups (as the UDFs) |
| `key_event(event)` | `(keyType, detail)` or `None` |
| `period_change(event)` | `PeriodStarted` / `PeriodEnded` or `None` |
| `stat_deltas(event)` | The event's contribution to each minute statistic |
| `minute_label(period, timeMin)` | Broadcast label, e.g. `45+2'` |

## 2. `pipeline.py`

*In short: a whole replay in, every table row and notification out.*

| Function | Produces |
| --- | --- |
| `stream_outputs(messages, window)` | The rows for all four tables and every notification the job should emit, using the same windows |
| `notification_body`, `message_id_for` | Exact Service Bus bodies and `MessageId`s |
| `stats_as_of(minute_rows, matches)` | What `matchStatsAsOf` should return, including `possessionPct` |

When a rule changes, change the query and this module together; the tests and `verify` will show any difference.
