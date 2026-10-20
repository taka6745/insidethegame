# Context

> **In short:** the shared match memory and everything the agents read. `compression.py` holds the pure rules that keep memory small; `render.py` turns ETL rows into compact prompt text; `builder.py` assembles each agent's prompt variables without reading past the horizon.

| | |
| --- | --- |
| **Status** | Implemented · tested |
| **Code** | [`narrative_engine/context/`](../../narrative_engine/context/): `compression.py`, `render.py`, `builder.py` |
| **Depends on** | [core models](core.md#1-match-clock-and-messages-modelspy), [match data](match-data.md), [store](store.md) |
| **Tests** | `test_compression.py` (design §5.4 checkpoints), `test_render.py` |

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

*In short: readable, compact text from the ETL's shapes, using the Opta codes in the ETL contracts.*

| Function | Output |
| --- | --- |
| `render_match` | Teams with home/away and short names |
| `render_events` | One line per event; passes counted per team, not listed, to keep a minute to a few lines |
| `render_stats` | Running totals per team as of a minute (goals, shots, possession share, cards…) |
| `render_ledger` | Key events in order, overturned goals marked |
| `describe_key_event` | The one-line reason used for a key-event step |

## 4. Prompt variables (`builder.py`)

*In short: one method per agent; every read is bounded.*

| Agent | Variables |
| --- | --- |
| Summariser | `game_state_statistics` (as of the minute), `match_events` (that minute) |
| Compressor | `game_state_statistics` (as of the span's end), `summaries` (the input blocks) |
| Author | `user_type`, `trigger_reason`, `game_state_statistics` (last summarised minute), `key_event_ledger`, `combined_match_context` (active blocks), `match_events` (since the last summary, up to the horizon), `narrative_excerpts` (the bucket's last 5) |

Statistics come from the last summarised minute, because a minute's statistics are only complete once its `MinuteClosed` has arrived. VAR overturns are resolved by looking up the overturned goal's event (`relatedEventId` is a per-team Opta `eventId`).
