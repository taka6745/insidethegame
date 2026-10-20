# SQL

> **In short:** two migrations: four tables the Stream Analytics job writes, with duplicate-tolerant keys, and the `matchStatsAsOf` view that turns per-minute deltas into running totals for any minute. The same scripts run on local SQL Server and Azure SQL.

| | |
| --- | --- |
| **Status** | Tested locally and in Azure against the reference |
| **Code** | [`sql/migrations/001_tables.sql`](../../sql/migrations/001_tables.sql), [`002_match_stats_as_of.sql`](../../sql/migrations/002_match_stats_as_of.sql) |
| **Applied by** | `python -m devtools migrate` (local) / `azure-setup` (Azure) |
| **Mirrors** | `reference/pipeline.py` `stats_as_of` |

## 1. Tables

*In short: typed columns for querying plus the full message for detail.*

| Table | Columns (besides `matchId`, `ingestedAt`) |
| --- | --- |
| `matches` | `description`, `homeContestantId`, `homeName`, `awayContestantId`, `awayName`, `scheduledKickoff`, `synthetic`, `payload` (full MA1) |
| `rawEvents` | `id`, `seq`, `eventId`, `typeId`, `periodId`, `timeMin`, `timeSec`, `contestantId`, `playerId`, `outcome`, `x`, `y`, `eventTime`, `payload` (full MA3) |
| `keyEvents` | `id`, `keyType`, `detail`, `typeId`, `contestantId`, `playerId`, `periodId`, `timeMin`, `timeSec`, `eventTime`, `relatedEventId` |
| `minuteStats` | `contestantId`, `periodId`, `timeMin`, `windowEnd`, `passes`, `passesCompleted`, `shots`, `shotsOnTarget`, `goals`, `ownGoals`, `corners`, `fouls`, `yellowCards`, `redCards`, `events` |

Primary keys use `IGNORE_DUP_KEY = ON` because Stream Analytics delivers at least once. `rawEvents` has an index on the match clock.

## 2. `matchStatsAsOf` view

*In short: running totals per team at every minute that had events.*

1. Sum `minuteStats` per team and minute (a window rarely splits a minute, but the view copes).
2. Build a grid of every minute with events for both teams, so a quiet team keeps its totals.
3. Running sums in match order give totals as of the end of each minute.
4. `goals` credits own goals to the opponent and subtracts VAR overturns; `ownGoals` counts goals a team put in its own net.
5. Adds `position` (home/away), `minuteLabel` (`45+2'`) and `possessionPct` (share of passes).

Consumers filter by minute for "as of", or order by period and minute descending and take two rows for "now".
