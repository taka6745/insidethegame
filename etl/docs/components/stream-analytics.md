# Stream Analytics

> **In short:** the whole ETL transformation in one Stream Analytics query. It reads Event Hubs by event time, detects key events with Opta rules, aggregates per-minute team statistics in tumbling windows, and writes nine SQL tables plus one Service Bus output. A second read of the same hub, in send order, writes watermark marks that Azure SQL turns into `matchProgress`. Seven small JavaScript UDFs read Opta qualifiers and shape rows.

| | |
| --- | --- |
| **Status** | Runs real-time matches on Azure with every output, the `match-progress` input and the Azure SQL triggers ([sql](sql.md#5-azure-only-stream-analytics-rows)). Progress lookback is 10 minutes and sessions are capped at 4 hours: a one-day bound ran the job out of memory (`test_azure_parity.py` checks the bounds) |
| **Runs** | Only while matches play: the [stream schedule](#6-run-only-while-matches-play) starts and stops it |
| **Code** | [`stream-analytics/query.asaql`](../../stream-analytics/query.asaql), [`stream-analytics/udfs/src/`](../../stream-analytics/udfs/src/) (TypeScript; `./dev udfs` compiles each to the plain `function main` `.js` Terraform uploads) |
| **Job** | StandardV2, ⅓ streaming unit, compatibility 1.2, created stopped |
| **Mirrors** | [reference](reference.md) (`opta.py`, `pipeline.py`) |
| **Tests** | `test_udfs.py`, `test_azure_parity.py` (UDFs under Node equal the reference; the reference equals [local stream](local-stream.md) on all three recordings), `test_sql_azure.py` (the triggers on SQL Server) |

## 1. Query structure

*In short: a chain of named steps, then nine SQL outputs and one Service Bus output.*

| Step | Does |
| --- | --- |
| `Stream` | Input `match-events`, `TIMESTAMP BY timeStamp` |
| `Events` | MA3 events with typed columns, the full message as `payload`, qualifier flags (penalty, own goal, cards, blocked, related event, VAR outcome) |
| `KeyCandidates` → `Detected` | `keyType` and `detail` from type and qualifiers; only rows with a key type |
| `MatchInfo` | MA1 message → teams and home/away via `udf.matchInfo` |
| `Rosters` | MA1 → `udf.matchTeams` and `udf.matchPlayers` arrays, expanded with `GetArrayElements` |
| `Canonical` | `MatchEvent` v2 (no `feed`; envelope `matchId`/`seq` must equal the event's) → `udf.canonicalEvent` |
| `Sent` → `SentSoFar` | Input `match-progress` (no `TIMESTAMP BY`, so arrival = send order): per match, the highest event seq, MA3 seq and POS sampleId sent so far (`MAX … OVER (PARTITION BY matchId … WHEN …)`) |
| `ProgressMarks` | MatchEvent *s* marks *s − 1*; a POS sample marks the latest event; a per-match `SessionWindow` closed by `idle_seconds` of quiet marks the last one ([why](#5-watermarks)) |
| `NotificationRows` | `KeyEventDetected`, `MinuteClosed` (one per window per period) and `PeriodStarted`/`PeriodEnded`, unioned with one shared column set |

| Output | Target |
| --- | --- |
| `matches` | SQL table, from `MatchInfo` |
| `rawEvents` | SQL table, from `Events` |
| `keyEvents` | SQL table, from `Detected` |
| `minuteStats` | SQL table, grouped by match, team, period, minute and window |
| `notifications` | Service Bus `match-notifications`; property `notificationType`, `MessageId` from `messageId` |
| `possessionSamples` | SQL table, POS messages |
| `matchTeams`, `matchPlayers` | SQL tables, from `Rosters` |
| `canonicalEvents` | SQL table, from `Canonical` |
| `matchProgressMarks` | SQL table, from `ProgressMarks`; Azure SQL advances `matchProgress` from it |

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
| Quiet spell | `watermark_idle_seconds` = 3 (rendered as `idle_seconds`) | Completes a match's last event, like the local worker's `ETL_WATERMARK_IDLE_SECONDS` |
| Out of order | Adjust, 2 s | Small reorderings within a minute |
| Late arrival | 5 s | Less than one replay minute |
| Output errors | Drop | One bad row must not stall every output; verification catches gaps |

For a real-time match set `window_seconds = 60` (and consider larger late-arrival tolerance), stop the job and apply Terraform.

## 4. UDFs

*In short: small helpers the query language lacks, written in TypeScript and compiled to plain scripts.*

Edit `udfs/src/*.ts`, then run `./dev udfs`: `tsc` (`udfs/tsconfig.json`, ES2015, no module code) emits one `function main` per file and `build.ts` adds a "generated, do not edit" header. `test_udfs.py` and CI fail if a `.js` is out of date.

| UDF | Returns |
| --- | --- |
| `hasQ(qualifiers, id)` | 1 if the qualifier is present |
| `qValue(qualifiers, id)` | The qualifier's value, or null |
| `matchInfo(message)` | A `matches` row from MA1 (home/away by position, full payload) |
| `toJson(message)` | The original message without fields Stream Analytics adds |
| `matchTeams(message)`, `matchPlayers(message)` | `matchTeams` / `matchPlayers` rows from MA1 (colours from `branding`) |
| `canonicalEvent(message)` | A `canonicalEvents` row from `MatchEvent` v2 |

## 5. Watermarks

*In short: the job only says what was sent; Azure SQL decides what is committed.*

The [local worker](local-stream.md) commits rows and the watermark in one transaction. Stream Analytics writes each output separately, so the job cannot know when another output's rows are in SQL. It writes marks instead: (`seq`, highest MA3 `seq`, highest POS `sampleId` sent so far). Event Hubs keeps send order per partition (`matchId`), and the feed sends an event's MA3 rows before the next event, so these numbers cover everything the watermark promises. The marks read the hub a second time without `TIMESTAMP BY` (consumer group `stream-analytics-progress`) because MA3 timestamps follow the match clock, not send order. The "sent so far" highs look back 10 minutes and the quiet-spell sessions last at most 4 hours: `MAX … OVER` holds every row of its window in memory and a start reads back the longest window, so the earlier one-day bounds ran the job out of memory on a hub holding a day of demos (23 Oct; no marks, so no watermark). `test_azure_parity.py` checks no recording goes that long without each kind of message.

Azure SQL's `INSTEAD OF INSERT` triggers advance `matchProgress` to the highest mark whose events `1..seq`, MA3 rows `1..ma3Seq` and POS samples `1..sampleId` are all stored, whichever output lands last. This relies on the feed numbering canonical events, MA3 rows and POS samples 1, 2, 3… per match ([contracts](../../../local/contracts/README.md#1-identity-and-snapshots)). `reference/pipeline.py` (`progress_marks`, `watermark`, `match_status`) is the expected result.

Not equal to local: Service Bus notifications for a match purged while live keep flowing until its feed run stops (the narrative engine drops them by its own tombstones), and rows stamped after a purge-all cut-off for a match whose MA1 was never stored are kept until the next purge.

## 6. Run only while matches play

*In short: Event Hubs traffic starts the job; 30 quiet minutes stop it (spend guard).*

[`infra/stream_schedule.tf`](../../infra/stream_schedule.tf): two metric alerts on `match-events` call webhooks of the `terraform/guard` runbook.

| Alert | Fires | Action |
| --- | --- | --- |
| `stream-start` | Incoming messages > 0 in the last minute | `stream-start`: start, resuming after the last output, so events buffered while it starts are processed (kick-off a minute or two late, then caught up) |
| `stream-stop` | None for `stream_idle_window` (default `PT30M`, longer than half time) | `stream-stop` |

The guard's last resort (90 % of the credit) also stops the job; `./dev azure up` restores it ([spend guard](../../../terraform/docs/components/guard.md)). Demo control's Start also asks the guard to start the job at once rather than wait for the traffic alert.
