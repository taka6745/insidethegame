# Context

> **In short:** the shared match memory and everything the agents read. `compression.py` holds the pure rules that keep memory small; `render.py` turns ETL rows into compact prompt text; `builder.py` assembles each agent's prompt variables without reading past the horizon.

| | |
| --- | --- |
| **Status** | Implemented · tested |
| **Code** | [`narrative_engine/context/`](../../narrative_engine/context/): `compression.py`, `render.py`, `builder.py` |
| **Depends on** | [core models](core.md#1-match-clock-and-messages-modelspy), [match data](match-data.md), [store](store.md) |
| **Tests** | `test_compression.py` (design §5.4 checkpoints), `test_render.py` (snapshots over the Riverton Rovers–United SPADL fixture), `test_recording_run.py` (whole match, backlog equals live) |

## 1. Decaying-resolution memory

*In short: recent minutes in detail, older play in ever larger blocks, never across half time.*

| Level | Block | Made by |
| --- | --- | --- |
| 0 | One minute | Minute summariser (or a fixed text for an empty minute) |
| 1 | Five minutes | Compressor, from five minute blocks |
| 2 | Earlier | Compressor, from two five-minute blocks plus any earlier block |

Replaced blocks stay in Cosmos with `supersededBy` set, so the report can show what each compression replaced. Active blocks always cover the match from kickoff to the last summarised minute with no gaps or overlaps.

## 2. Compression rules

*In short: two counting rules within the current period, plus a collapse at period end.*

1. At 11 minute blocks in the current period, compress the oldest 5 into a five-minute block.
2. At 4 five-minute blocks in the current period, merge the oldest 2 and any earlier block into one earlier block.
3. When a period ends, `close_period` merges all of its blocks into one earlier block for that period.

The rules are pure functions (`next_compression`, `apply`, `close_period`, `compress_all`) with no I/O, so the whole schedule is unit tested.

## 3. Prompt text (`render.py`)

*In short: readable, compact text in SPADL terms; facts SPADL leaves out come from key events and MA3.*

| Function | Output |
| --- | --- |
| `render_match` | Teams with home/away and short names |
| `render_events` | SPADL actions under a heading per minute: `12:31 RVR Ashworth: cross, success, left foot, right wing → box`. Passes, throw-ins, goal kicks and carries (SPADL's inferred dribbles) are counted, not listed: a `totals:` line per minute gives each team's pass-family completion, carries and final-third and box entries. A `keeper_save` flagged `defensiveBlock` or `fromShotOffTarget` is labelled an outfield block or a touch of a shot going wide, not a goalkeeper save. Key events (goals, red cards, penalties, VAR) come from `keyEvents`; yellow cards, substitutions and period start/end from MA3 |
| `render_stats` | The SPADL catalogue (`executeStatsAtSeq`) as a table: possession (ball time), shots (on target), passes (completed), crosses (completed), final-third and box entries, corners, fouls, cards; the score from `keyEvents` (own goals for the opponent, VAR overturns removed); then each shown stat's catalogue `definition` ("What each counts"). `render_ledger` gives the score after each goal |
| `render_ledger` | Key events in order, overturned goals marked |
| `describe_key_event` | The one-line reason used for a key-event step |
| `render_trends` | ETL trend rows per window and team: `[last15: last 15 minutes] Riverton Rovers (RVR): field_tilt 0.78 (high, rising from 0.63); box_entries 7.00/5min (high); …` (indicator ids, rates marked `/5min` and heights `m`); the author gets only flagged rows plus whole-match dominance and possession |
| `render_trend_table` | The analyst's table: a `Teams:` line, then per window (`window "last15" (last 15 minutes):`) one line per indicator with both teams side by side, `  def_height: RVR 52.6m (notable) \| FGU 37.1m`, in the fields and values an evidence item cites |
| `render_spells` | Territory and pressure spells, when enabled |
| `render_storylines` | Storylines with their last beats and linked key events; ids and labels for the analyst, the focus marked `FOCUS` for the author |

## 4. Prompt variables (`builder.py`)

*In short: one method per agent; every read is bounded.*

| Agent | Variables |
| --- | --- |
| Summariser | `game_state_statistics` (as of the minute), `match_events` (that minute) |
| Compressor | `game_state_statistics` (as of the span's end), `summaries` (the input blocks) |
| Analyst | `analysis_reason`, `game_state_statistics`, `key_event_ledger`, `combined_match_context`, `match_trends` (`render_trend_table` at the analysis's seq, plus goals and red cards per team as citable rows, and spells), `storylines` |
| Author | `user_type`, `trigger_reason`, `game_state_statistics` (last summarised minute), `key_event_ledger`, `combined_match_context` (the blocks up to the horizon), `match_events` (since the last of them, up to the horizon), `narrative_excerpts` (the bucket's last 5 written from data up to the horizon), `storylines` and `match_trends` (once per step, shared by its buckets) |

Context blocks are the active blocks, cut at the horizon (`blocks`): a minute counts once it is over by then (the horizon's own minute only at its last second or a period end), so a step recorded after later minutes were summarised (messages handled out of order) reads the superseded blocks up to its horizon instead of a later merge. Statistics come from the last of those minutes, because a minute's statistics are only complete once its `MinuteClosed` has arrived; they are read at that minute's last canonical seq. A window of play holds the actions settled in it (`finalSeq` after the seq at the end of the previous minute, up to the window's seq), so an action settled by the next minute's first action is shown there, under that minute's heading with its own time, and every action appears exactly once. A key-event step reads up to the key event's own MA3 row; other steps up to the latest row at their horizon. Sizes over Riverton Rovers–United (o200k tokens): a minute's events 153 → 152 mean, the stats table 159 → 191, the prompt templates +135 for the SPADL glossary. VAR overturns are resolved by looking up the overturned goal's event (`relatedEventId` is a per-team Opta `eventId`).
