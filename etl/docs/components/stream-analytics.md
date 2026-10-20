# Stream Analytics

> **In short:** the whole ETL transformation in one Stream Analytics query. It reads Event Hubs by event time, detects key events with Opta rules, aggregates per-minute team statistics in tumbling windows, and writes four SQL tables plus one Service Bus output. Four small JavaScript UDFs read Opta qualifiers and copy messages.

| | |
| --- | --- |
| **Status** | Deployed (dev); output matches the reference on a 10x replay |
| **Code** | [`stream-analytics/query.asaql`](../../stream-analytics/query.asaql), [`stream-analytics/udfs/`](../../stream-analytics/udfs/) |
| **Job** | StandardV2, ⅓ streaming unit, compatibility 1.2, created stopped |
| **Mirrors** | [reference](reference.md) (`opta.py`, `pipeline.py`) |
| **Tests** | `test_udfs.py` (UDFs run under Node against generated events) |

## 1. Query structure

*In short: a chain of named steps, then five outputs.*

| Step | Does |
| --- | --- |
| `Stream` | Input `match-events`, `TIMESTAMP BY timeStamp` |
| `Events` | MA3 events with typed columns, the full message as `payload`, qualifier flags (penalty, own goal, cards, blocked, related event, VAR outcome) |
| `KeyCandidates` → `Detected` | `keyType` and `detail` from type and qualifiers; only rows with a key type |
| `MatchInfo` | MA1 message → teams and home/away via `udf.matchInfo` |
| `NotificationRows` | `KeyEventDetected`, `MinuteClosed` (one per window per period) and `PeriodStarted`/`PeriodEnded`, unioned with one shared column set |

| Output | Target |
| --- | --- |
| `matches` | SQL table, from `MatchInfo` |
| `rawEvents` | SQL table, from `Events` |
| `keyEvents` | SQL table, from `Detected` |
| `minuteStats` | SQL table, grouped by match, team, period, minute and window |
| `notifications` | Service Bus `match-notifications`; property `notificationType`, `MessageId` from `messageId` |

## 2. Key-event rules

*In short: Opta type plus qualifier decides the key type.*

| keyType | Rule |
| --- | --- |
| `Goal` (`detail` `penalty`) | type 16 without qualifier 28 |
| `OwnGoal` | type 16 with qualifier 28 |
| `PenaltyAwarded` (`conceded`) | type 4, outcome 0, qualifier 9 |
| `PenaltyMissed` | types 13/14/15 with qualifier 9 |
| `RedCard` (`second-yellow`) | type 17 with qualifier 32 or 33 |
| `VarOverturn` | type 900 with qualifier 901 = `goal-overturned`; also a −1 goal delta |

## 3. Timing settings

*In short: tuned for 10x replays.*

| Setting | Value | Why |
| --- | --- | --- |
| Tumbling window | `window_seconds` = 6 (Terraform variable, rendered into the query) | One match minute at 10x |
| Out of order | Adjust, 2 s | Small reorderings within a minute |
| Late arrival | 5 s | Less than one replay minute |
| Output errors | Drop | One bad row must not stall every output; verification catches gaps |

For a real-time match set `window_seconds = 60` (and consider larger late-arrival tolerance), stop the job and apply Terraform.

## 4. UDFs

*In short: small helpers the query language lacks.*

| UDF | Returns |
| --- | --- |
| `hasQ(qualifiers, id)` | 1 if the qualifier is present |
| `qValue(qualifiers, id)` | The qualifier's value, or null |
| `matchInfo(message)` | A `matches` row from MA1 (home/away by position, full payload) |
| `toJson(message)` | The original message without fields Stream Analytics adds |
