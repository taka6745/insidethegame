# SQL

> **In short:** eighteen migrations (`001`–`018`): the tables the Stream Analytics job writes, with duplicate-tolerant keys; the `matchStatsAsOf` view (running totals per minute); the multi-match read models (teams, players, canonical events, possession samples, watermarks, purge tombstones); the job's watermark marks; SPADL actions; the stat catalogue on SPADL (`statDefinitions` + `statsAtSeq`); and trend indicators (`trendDefinitions` + three procedures). The same scripts run on local SQL Server and Azure SQL. One Azure-only script adds the triggers that gate and advance Stream Analytics' rows.

| | |
| --- | --- |
| **Status** | Tested against the reference on SQL Server 2025-CU9 · `001`–`018` and `azure/asa-progress.sql` applied on Azure SQL by `azure-setup` |
| **Code** | [`001_tables.sql`](../../sql/migrations/001_tables.sql), [`002_match_stats_as_of.sql`](../../sql/migrations/002_match_stats_as_of.sql), [`003_multi_match.sql`](../../sql/migrations/003_multi_match.sql), [`004_stat_catalogue.sql`](../../sql/migrations/004_stat_catalogue.sql), [`005_read_committed_snapshot.sql`](../../sql/migrations/005_read_committed_snapshot.sql), [`006_progress_marks.sql`](../../sql/migrations/006_progress_marks.sql), [`007_spadl_actions.sql`](../../sql/migrations/007_spadl_actions.sql), [`008_spadl_catalogue.sql`](../../sql/migrations/008_spadl_catalogue.sql), [`009_spadl_stats_staged.sql`](../../sql/migrations/009_spadl_stats_staged.sql), [`010_raw_event_seq.sql`](../../sql/migrations/010_raw_event_seq.sql), [`011_trend_definitions.sql`](../../sql/migrations/011_trend_definitions.sql), [`012_trends_at_seq.sql`](../../sql/migrations/012_trends_at_seq.sql), [`013_team_known_names.sql`](../../sql/migrations/013_team_known_names.sql), [`014_trend_patterns.sql`](../../sql/migrations/014_trend_patterns.sql), [`015_trend_parameters.sql`](../../sql/migrations/015_trend_parameters.sql), [`016_trend_parameters_guard.sql`](../../sql/migrations/016_trend_parameters_guard.sql), [`017_entry_definitions.sql`](../../sql/migrations/017_entry_definitions.sql), [`018_trend_labels.sql`](../../sql/migrations/018_trend_labels.sql); Azure only: [`azure/asa-progress.sql`](../../sql/azure/asa-progress.sql) |
| **Applied by** | `python -m devtools migrate` (local) / `azure-setup` (Azure: migrations, then `sql/azure/`) / `local_stream/init-sql.sh` (shared stack) |
| **Mirrors** | `reference/pipeline.py` `stats_as_of`; `reference/catalogue.py` `stats_at_seq`; `reference/trends.py` |

## 1. Tables

*In short: typed columns for querying plus the full message for detail.*

| Table | Columns (besides `matchId`, `ingestedAt`) |
| --- | --- |
| `matches` | `description`, `homeContestantId`, `homeName`, `awayContestantId`, `awayName`, `scheduledKickoff`, `synthetic`, `payload` (full MA1) |
| `rawEvents` | `id`, `seq`, `eventId`, `typeId`, `periodId`, `timeMin`, `timeSec`, `contestantId`, `playerId`, `outcome`, `x`, `y`, `eventTime`, `payload` (full MA3), `eventSeq` (canonical seq, `010`) |
| `keyEvents` | `id`, `keyType`, `detail`, `typeId`, `contestantId`, `playerId`, `periodId`, `timeMin`, `timeSec`, `eventTime`, `relatedEventId` |
| `minuteStats` | `contestantId`, `periodId`, `timeMin`, `windowEnd`, `passes`, `passesCompleted`, `shots`, `shotsOnTarget`, `goals`, `ownGoals`, `corners`, `fouls`, `yellowCards`, `redCards`, `events` |

Primary keys use `IGNORE_DUP_KEY = ON` because Stream Analytics delivers at least once. `rawEvents` has indexes on the match clock and, from `010`, on `(matchId, eventSeq)` for snapshot-bounded reads.

## 2. `matchStatsAsOf` view

*In short: running totals per team at every minute that had events.*

1. Sum `minuteStats` per team and minute (a window rarely splits a minute, but the view copes).
2. Build a grid of every minute with events for both teams, so a quiet team keeps its totals.
3. Running sums in match order give totals as of the end of each minute.
4. `goals` credits own goals to the opponent and subtracts VAR overturns; `ownGoals` counts goals a team put in its own net.
5. Adds `position` (home/away), `minuteLabel` (`45+2'`) and `possessionPct` (share of passes).

Consumers filter by minute for "as of", or order by period and minute descending and take two rows for "now".

## 3. Multi-match read models (003)

*In short: what [local contracts §3](../../../local/contracts/README.md#3-etl-graphql-dab) serves, keyed by `matchId`.*

| Object | One row per | Written from |
| --- | --- | --- |
| `matches` + `fixture sourceMatchId runId status capabilities` | match | MA1; `status` by the stream worker (Azure: the triggers) |
| `matchTeams`, `matchPlayers` | contestant, lineup player | MA1 `contestant[]`, `branding` |
| `canonicalEvents` | `MatchEvent` v2 (`seq`) | MatchEvent v2; corrections are new seqs |
| `possessionSamples` | POS sample | POS |
| `matchProgress` → view `matchWatermarks` | match | the stream worker (Azure: the triggers, from `matchProgressMarks`) |
| `matchProgressMarks` (006) | job mark | Stream Analytics; consumed by the triggers, empty locally |
| `purgedMatches`, `purgeCutoff` | tombstone; one cut-off | `POST /admin/matches/purge` |
| `spadlActions`, `spadlProgress` (007) | final SPADL action; match | the [SPADL post-processor](spadl.md); `matchWatermarks.spadlSeq` reads `spadlProgress` |

## 4. Stat catalogue (004, redefined on SPADL by 008 and 009)

*In short: definitions are configuration; one procedure computes every stat for a snapshot.*

`008` replaces `004`'s table; `009` replaces the procedure and adds the `spadlActions` save qualifiers (`fromShotOffTarget`, `defensiveBlock`) and an index on `rawEvents (matchId, typeId)`. `statDefinitions` is seeded with 42 kinds (`009` adds `shots_saved`, real goalkeeper saves, to databases that applied `008` before it) ([local contracts §4](../../../local/contracts/README.md#4-stat-catalogue), including the old → new mapping); its header comment defines each `counter` and `requires` token. `statsAtSeq(@matchId, @seq)` counts `spadlActions` with `finalSeq ≤ @seq` by the enabled definitions for both teams and each contestant, cards from MA3 card rows and VAR goal overturns (type 900) with `eventSeq ≤ @seq`, possession from samples up to that event's video time, and checks availability against MA1 `capabilities`. Percentages round like Python's `round(x, 1)` (`roundHalfEven1`). Unknown match or `@seq` above the watermark or `spadlSeq`: no rows. It runs in stages over table variables (capabilities and definitions parsed once, final actions grouped before they meet the definitions): about 60 ms of CPU at full time on an emulated SQL Server 2025, against about 200 ms for the single statement. DAB needs `EXECUTE` on the procedure (granted by `devtools azure-setup`). `010` adds the indexed `rawEvents.eventSeq` column (backfilled from the payload) and recreates the procedure to read it and to treat an undeclared `shotOutcomes` capability as unavailable.

`005` turns on read-committed snapshot where it is off (Azure SQL already has it), so DAB reads never deadlock with the stream's batch transactions.

`011` adds `trendDefinitions` (seeded through `seedTrendDefinitions`) and `012` the read-time trend procedures `trendMinutesAtSeq`, `trendsAtSeq` and `trendSpellsAtSeq` over the function `trendMinuteRows`; `014` recreates them with flanks, fade and game state and reseeds ([trends](trends.md)); `015` adds `trendParameters` (ball-time cap, long-pass length, fast-break limits, momentum alpha, build-up and pressing lines, flank lanes, threat weights; seeded through `seedTrendParameters`) and recreates `trendMinuteRows` to read them. `016` makes that procedure refuse a block missing any name the function reads; `017` rewrites the box-entry and final-third-entry definitions (the counters are not nested); `018` gives two trends plain labels.

## 5. Azure only: Stream Analytics rows

*In short: triggers do on Azure SQL what the local worker does in Python.*

Stream Analytics only appends, one output at a time; Microsoft documents `INSTEAD OF INSERT` triggers for intercepting its inserts. `azure/asa-progress.sql` adds one per table the job writes:

| Job | How |
| --- | --- |
| Tombstones | Rows of a purged match are dropped. An MA1 stamped before the purge-all cut-off tombstones its match and drops its rows (SPADL rows included); other rows stamped before the cut-off need a stored MA1. The SPADL post-processor checks the tombstone itself under the same lock |
| Watermark | `asaProgress` moves `matchProgress` to the highest mark whose events `1..seq`, MA3 rows `1..ma3Seq` and POS samples `1..sampleId` are stored, deletes consumed marks, and sets `status` (`live` once an event is stored, `finished` at the final `period_end`) |
| Concurrency | Inserts hold applock `etl-purge` shared and the purge holds it exclusive; `asaProgress` holds a per-match lock, so the last of several concurrent output batches sees them all |

`006` adds `matchProgressMarks` and an index on `rawEvents (matchId, seq)` everywhere; locally the table stays empty and there are no triggers. `test_sql_azure.py` inserts the reference's rows as independent batches (marks first, outputs interleaved, in parallel) and checks watermark, status, `statsAtSeq` and purges.
