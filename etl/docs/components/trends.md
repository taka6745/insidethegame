# Trends

> **In short:** read-time SQL procedures that say who controls a match, per team and window, as of any snapshot: 23 window indicators and composites, momentum and two kinds of spell. Formulas are fixed in SQL and in a Python twin; thresholds and whether a trend may be claimed live in the `trendDefinitions` table. The narrative engine's analyst reads them through DAB.

| | |
| --- | --- |
| **Status** | Implemented · tested against SQL Server 2022 and 2025-CU9 (parity with the reference on all three recordings) · not yet run on the shared stack or Azure |
| **Code** | [`011_trend_definitions.sql`](../../sql/migrations/011_trend_definitions.sql) (table, seed), [`014_trend_patterns.sql`](../../sql/migrations/014_trend_patterns.sql) (procedures, columns, the current seed; replaces `012`), [`015_trend_parameters.sql`](../../sql/migrations/015_trend_parameters.sql) (`trendParameters`: the formulas' constants; `trendMinuteRows` reads them), [`018_trend_labels.sql`](../../sql/migrations/018_trend_labels.sql) (plain labels for writers), [`devtools/calibrate_trends.py`](../../devtools/calibrate_trends.py) (thresholds from the recordings), [`reference/trends.py`](../../reference/trends.py) |
| **Served as** | DAB `trendDefinitions`, `executeTrendsAtSeq`, `executeTrendSpellsAtSeq`, `executeTrendMinutesAtSeq` ([contract](../../contracts/README.md#output-4-trend-indicators)) |
| **Definitions** | [local contracts §4b](../../../local/contracts.md#4b-trend-definitions) |
| **Tests** | `test_trends.py` (rules, golden), `test_sql_trends.py` (SQL = reference, bounds, VAR game state, re-seed, speed) |

## 1. How it works

*In short: one function builds minute rows; three procedures read them.*

```text
canonicalEvents ≤ s ─ minutes, video time ┐
possessionSamples ≤ video(s) ─────────────┤
spadlActions finalSeq ≤ s ─ ball, entries ├─▶ trendMinuteRows ─┬─▶ trendMinutesAtSeq
rawEvents eventSeq ≤ s ─ defence, cards ──┘   (minute × team)  ├─▶ trendsAtSeq (windows, flags)
trendDefinitions ─ thresholds ─────────────────────────────────┴─▶ trendSpellsAtSeq
```

- `dbo.trendMinuteRows(@matchId, @seq)` (multi-statement table function) returns one row per minute and team: components, threat, momentum (a loop over the minutes) and the spell minute flags. Each procedure stores it once in a `dbo.trendMinute` table variable.
- Nothing is materialised: every call recomputes from the rows final at the snapshot, so a backlog read equals the live one and purging the match's rows removes everything.
- Bounds as `statsAtSeq`: empty for an unknown match or `@seq` above `matchWatermarks.seq` or `spadlSeq`.
- No Stream Analytics change: on Azure the same migrations run on Azure SQL; `devtools azure-setup` grants DAB `EXECUTE` on the three procedures.

## 2. Windows and flags

*In short: the current period's last 5 and 15 minutes, the half and the match, each against a baseline.*

| Window | Minutes | Baseline (`delta = value − baseline`) | Flags from |
| --- | --- | --- | --- |
| `last5` | current period's last 5 | `prev10` | 5 minutes |
| `prev10` | the 10 before `last5` | – | 10 |
| `last15` | current period's last 15 | the match before `last15` | 15 |
| `half` | current period | previous period | 5 |
| `match` | all | – | 5 |

`level`: `high` at or above `highAt`, `notable` at or above `notableAt` (at or below for `direction` `low`, e.g. `ppda`). `change`: `rising`/`falling` when `|delta| ≥ changeAt` and the baseline has at least 10 minutes. `flagged` = `high` or a change. Flags need `enabled`; disabled trends keep their values. Momentum has one `last5` row: now against the minute before `last5`.

Served in one window only, without a baseline: `territory_fade` in `last15` (the attacking-half share of the 15 minutes before it in the period minus last15's; null without all 15) and `att_half_leading` / `att_half_trailing` in `half` (attacking-half share over the period's minutes the team started ahead / behind; null with fewer than `minMinutes`).

## 3. Spells and momentum

*In short: runs of strong minutes, and a smoothed threat difference.*

- A minute is a territory (pressure) minute when it has at least `minBallSeconds` of ball time and an attacking-half (final-third) share at or above `minuteAt`; a pressure minute also needs an entry or a shot.
- A spell is a run of such minutes within a period that bridges single other minutes, at least `minMinutes` long. Rows give its span, zone share, shots, box entries and `ongoing` (it reaches the latest minute). A spell whose definition `requires` another kind (pressure needs territory) is `enabled` only while it overlaps a spell of that kind of the same team.
- Momentum: EWMA (α `momentum_alpha`, seeded 0.4) of home − away threat per minute from kick-off.

## 4. Seeded state and evidence

*In short: the scripted-tactics recordings support control, style, flank, fade and game-state claims and territory spells; not momentum.*

The S1 v2 experiment (permutation tests over shuffled minutes, team distinctness, calibration on the three scripted-tactics recordings) seeded `014`: possession, field tilt, attacking-half and final-third share, defensive height, box entries, dominance, PPDA (low end), directness, both flanks, the late fade and territory by game state enabled, with thresholds from `devtools.calibrate_trends` (the outer 20% / 10% of served values in the trend's direction; change at the 90th percentile of |delta|); shots, box shots, final-third entries, fouls and cards enabled as counts (cards: no thresholds, any card is a key event); territory spells enabled, pressure spells only alongside territory (`requires`); contests, aggression, fast breaks, long-ball share and momentum disabled. Each row's `evidence` says why.

## 5. Re-seeding

*In short: one JSON block per migration; the newest wins.*

`dbo.seedTrendDefinitions @definitions` replaces the whole table from a JSON array (missing rows are deleted; `displayOrder` follows the array). To apply new thresholds or enabled flags (for example from a new experiment report):

1. Copy the newest block (`014`); recalibrate with `python -m devtools.calibrate_trends` after the recordings change.
2. Add `NNN_trend_seed_<what>.sql` that declares the edited array as `@trendDefinitions` and passes it to `dbo.seedTrendDefinitions`.
3. `reference/trends.py` reads the newest `@trendDefinitions` and `@trendParameters` blocks, so `python -m pytest tests/test_trends.py tests/test_sql_trends.py` checks the new seed; regenerate the golden file with `python tests/test_trends.py --regenerate` if values or flags changed.

Labels change without re-seeding: a migration declaring `@trendLabels` (trendId, label) updates them, and `reference/trends.py` applies those blocks after the newest seed (`018`: writers see labels and meanings, never ids, so labels are plain football words).

Formula constants re-seed the same way: a migration declaring the whole `@trendParameters` block and passing it to `dbo.seedTrendParameters` (newest block: `015`); since `016` the procedure refuses a block that misses, misspells or nulls any of the 13 names `trendMinuteRows` reads, and leaves the table unchanged; recalibrate the thresholds after changing one, since it changes what the trends measure.

## 6. Performance

*In short: a few hundred milliseconds on an emulated server, set-based except the momentum loop.*

At full time (Chelsea–United before its 2026-10-22 re-render: 11,392 events, 2,963 actions, 5,356 samples; now 11,133, 2,710 and 5,198) each procedure took 220–420 ms on SQL Server 2022 under x86 emulation on an Apple-silicon laptop with the CPU busy (`statsAtSeq`: 75–170 ms there); `test_sql_trends.py` fails above 500 ms. Native SQL Server is several times faster. The window functions over the final actions (next action, chain start, first entries) and the table-variable inserts dominate.
