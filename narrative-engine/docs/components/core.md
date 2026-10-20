# Core

> **In short:** the engine's rules. `models.py` defines the match clock, the ETL messages and the stored records; `config.py` holds the tunable settings; `orchestrator.py` decides what runs when for one match and keeps that decision in a Cosmos checkpoint.

| | |
| --- | --- |
| **Status** | Implemented · tested |
| **Code** | [`narrative_engine/core/`](../../narrative_engine/core/): `models.py`, `config.py`, `orchestrator.py` |
| **Depends on** | [context](context.md), [agents](agents.md), [match data](match-data.md), [store](store.md), a publisher from [transport](transport.md) |
| **Tests** | `test_models.py`, `test_orchestrator.py` |

## 1. Match clock and messages (`models.py`)

*In short: the ETL's Opta clock, typed messages and the records the engine stores.*

### 1.1 `MatchClock`

`(periodId, timeMin)`, ordered by period then minute. `timeMin` is 0-based; first-half added time continues (46 = `45+2'`) and the second half restarts at 45, so a minute is unique only with its period. `label` gives the broadcast label (`24'`, `45+3'`), `key` a stable string for IDs, and `next()` the following minute.

### 1.2 Messages

| Class | From | Key fields |
| --- | --- | --- |
| `MinuteClosed` | ETL | `matchId`, `clock`, `windowEnd` |
| `KeyEventDetected` | ETL | `keyEvents` row: `id`, `keyType`, `detail`, `contestantId`, `playerId`, clock, `timeSec`, `relatedEventId` |
| `PeriodChanged` | ETL `PeriodStarted` / `PeriodEnded` | `periodId`, `started` |
| `PresenceChanged` | User backend | `activeUserTypes` counts, `sentAt` |

`parse_notification(body, messageType)` switches on `messageType`. Every ETL body carries every key, unused ones `null`.

### 1.3 Records

`Trigger` (why a step runs), `AgentResult` (text, model, prompt version, tokens), `ContextBlock` and `Narrative`. Field lists: [architecture §4](../architecture.md#4-data-model).

## 2. Settings (`config.py`)

*In short: five numbers that shape behaviour.*

| Setting | Default | Effect |
| --- | --- | --- |
| `last_n_narratives` | 5 | Previous narratives per bucket shown to the author |
| `fallback_minutes` | 10 | Summarised minutes without a step before a `scheduled` step |
| `author_concurrency` | 4 | Author calls in flight across buckets |
| `presence_stale_seconds` | 180 | Older presence falls back to all 12 buckets |
| `final_period` | 2 | Period whose end means full time (no extra time) |

## 3. Orchestrator (`orchestrator.py`)

*In short: record each message in the checkpoint, then work through the checkpoint in match-time order.*

### 3.1 Entry points

| Method | Use |
| --- | --- |
| `accept(message)` | Service: record, wake the background worker, return at once |
| `handle(message)` | Tests and local runs: record, then do the work before returning |
| `record(message)` | Update the checkpoint and queue steps; idempotent |
| `work()` | Do everything that is due, then return |
| `kick()` | Start the background worker if it is not running |

### 3.2 What `record` does per message

| Message | Recorded |
| --- | --- |
| `MinuteClosed` | `closedThrough` and `horizon` move forward |
| `KeyEventDetected` | `horizon` moves; a `keyEvent` step is queued, gated on the minutes closed so far |
| `PresenceChanged` | Presence updated (older `sentAt` ignored); a `catchUp` step for each bucket that went from 0 to 1+ |
| `PeriodChanged` | Saved; period ends are read from the ETL when needed |

### 3.3 The work loop

Under a per-match lock, repeat until nothing is due:

1. If a queued step is ready (its gate minute is summarised), run the one with the earliest horizon.
2. Else, if a closed minute is unsummarised, summarise it (empty minutes need no model call), compress, and queue a `scheduled` step if ten minutes have passed without one.
3. Else, if a period has ended, collapse its blocks and queue `halfTime` or `fullTime`.

The background worker retries failures with backoff doubling from 5 s up to 120 s. Work resumes after a restart because the queue is in the checkpoint.

### 3.4 Running a step

1. Rebuild the trigger reason (for key events from the stored row and match info).
2. For each of the step's buckets, under that bucket's lock and the global author limit: if a narrative for this step already exists, publish it again; otherwise build the author variables at the step's horizon, call the author, save the narrative with the next `seq`, then publish it.
3. Remove the step from `pending` and add its ref to `done`.

### 3.5 Identifiers

| Thing | ID |
| --- | --- |
| Block | `block:{matchId}:{level}:{start}:{end}` |
| Step | `{matchId}:{ref}`, refs `key:{eventId}`, `scheduled:{minute}`, `halfTime:1`, `fullTime:2`, `catchUp:{bucket}:{sentAt}` |
| Narrative | `narr:{matchId}:{userType}:{seq}` |
