# Core

> **In short:** the engine's rules. `models.py` defines the match clock, the ETL messages and the stored records; `config.py` holds the tunable settings; `orchestrator.py` decides what runs when for one match and keeps that decision in a Cosmos checkpoint.

| | |
| --- | --- |
| **Status** | Implemented · tested |
| **Code** | [`narrative_engine/core/`](../../narrative_engine/core/): `models.py`, `config.py`, `orchestrator.py`, `gate.py` (`ModelGate`: one cap on model calls across matches) |
| **Depends on** | [context](context.md), [agents](agents.md), [match data](match-data.md), [store](store.md), a publisher from [transport](transport.md) |
| **Tests** | `test_models.py`, `test_orchestrator.py` |

## 1. Match clock and messages (`models.py`)

*In short: the ETL's Opta clock, typed messages and the records the engine stores.*

### 1.1 `MatchClock`

*In short: a match minute is unique only with its period.*

`(periodId, timeMin)`, ordered by period then minute. `timeMin` is 0-based; first-half added time continues (46 = `45+2'`) and the second half restarts at 45, so a minute is unique only with its period. `label` gives the broadcast label (`24'`, `45+3'`), `key` a stable string for IDs, and `next()` the following minute.

### 1.2 Messages

*In short: what arrives from the ETL and the backend.*

| Class | From | Key fields |
| --- | --- | --- |
| `MinuteClosed` | ETL | `matchId`, `clock`, `windowEnd` |
| `KeyEventDetected` | ETL | `keyEvents` row: `id`, `keyType`, `detail`, `contestantId`, `playerId`, clock, `timeSec`, `relatedEventId` |
| `PeriodChanged` | ETL `PeriodStarted` / `PeriodEnded` | `periodId`, `started`, and the Start/End event's `clock`, `timeSec` when the body has them |

`parse_notification(body, messageType)` switches on `messageType` and returns `None` for any other type before reading a field (the topic is shared). Every ETL body carries every key, unused ones `null`.

Buckets are not messages: the orchestrator reads the user backend's current targets ([audience](#4-audience-targets)).

### 1.3 Records

*In short: what the engine stores and returns.*

`Trigger` (why a step runs), `AgentResult` (text, model, prompt version, tokens), `ContextBlock` and `Narrative`. Field lists: [architecture §4](../architecture.md#4-data-model).

## 2. Settings (`config.py`)

*In short: the tunables, each also read from its upper-case environment variable (`Settings.from_env`).*

| Setting | Default | Effect |
| --- | --- | --- |
| `last_n_narratives` | 5 | Previous narratives per bucket shown to the author |
| `fallback_minutes` | 10 | Summarised minutes without a step before a `scheduled` step |
| `author_concurrency` | 4 | One match's author calls in flight across its buckets |
| `model_concurrency` | 4 | Model calls in flight across all matches ([service §3](service.md#3-router)) |
| `final_period` | 2 | Period whose end means full time when MA1 has no `capabilities.periods` |
| `targets_poll_seconds` | 5 | Target re-read interval for live matches |
| `backend_cache_seconds` | 5 | Targets and prompts are revalidated (ETag) at most this often |
| `retry_seconds`, `retry_max_seconds` | 5, 120 | Backoff of failed or paused match work |
| `analysis_minutes` | 5 | A match analysis at minutes 5', 10', 15' … (plus half and full time) |
| `storyline_turns` | 1 | 1: a storyline an analysis opens or resolves gets a `storylineTurn` step; 0: off |

## 3. Orchestrator (`orchestrator.py`)

*In short: record each message in the checkpoint, then work through the checkpoint in match-time order.*

### 3.1 Entry points

*In short: `accept` for the service, `handle` for tests.*

| Method | Use |
| --- | --- |
| `accept(message)` | Service: record, wake the background worker, return at once |
| `handle(message)` | Tests and local runs: record, then do the work before returning |
| `record(message)` | Update the checkpoint and queue steps; idempotent |
| `work()` | Do everything that is due, then return |
| `kick()` | Start the background worker if it is not running |

### 3.2 What `record` does per message

*In short: each message moves the checkpoint and may queue steps.*

| Message | Recorded |
| --- | --- |
| `MinuteClosed` | `closedThrough` and `horizon` move forward |
| `KeyEventDetected` | `horizon` moves; a `keyEvent` step is queued, gated on the minutes closed so far |
| Any (and the router's 5 s poll) | Targets re-read; on a new revision a `catchUp` step for each newly enabled bucket; a disabled bucket gets no further steps |
| `PeriodChanged` (end) | The period's end and its last minute are closed at the End event's clock (from the body, else the ETL) |

### 3.3 The work loop

*In short: ready steps first, then summaries, then period closes.*

Under a per-match lock, repeat until nothing is due:

1. If a queued step is ready (its gate minute is summarised), run the one with the earliest horizon; at equal horizons a match analysis runs first, so the steps there read it.
2. Else, if a closed minute is unsummarised, summarise it (empty minutes, and merges of only empty minutes, need no model call), compress, queue a match analysis at minutes 5', 10', 15' …, and queue a `scheduled` step if ten minutes have passed without one. A period's last minute skips both (closing the period merges it and queues the half-time or full-time step); stoppage time queues no `scheduled` step.
3. Else, if a period has ended, collapse its blocks and queue its analysis and then `halfTime` or `fullTime`. `PeriodEnded` closes the period's last minute at once, at the End event's clock and second (no wait for `MinuteClosed` or the ETL's idle flush). That minute is summarised only once its End row is in ETL GraphQL (`EtlBehind` until then).

The background worker retries failures with backoff doubling from 5 s up to 120 s. Waiting for the backend (targets, prompts) or the ETL logs a warning, not a stack trace. Work resumes after a restart because the queue is in the checkpoint.

A match runs one step at a time; a step's author calls run together (up to `author_concurrency`), and one that fails leaves the others' narratives stored, so a retry redoes only the missing ones. Every agent call also takes a slot of the router's global `ModelGate`; decision calls do too unless the decision model has its own capacity. Analyses and storylines: [analysis](analysis.md); follow steps: [follows](follows.md).

### 3.4 Running a step

*In short: pin the inputs, write each bucket, mark the step done.*

1. Rebuild the trigger reason (for key events from the stored row and match info). On the first attempt, pin the author prompt, the seq, the latest analysis and the focus storyline ([analysis](analysis.md#2-storylines)).
   For a key event whose `keyType` is in the served `clips.key_types`, with `clips.enabled` and `clips.shared`, `_publish_moment_clip` first sends one `MomentClip` for the step's buckets ([contract](../../contracts/README.md#key-event-clips-type-momentclip)). It is sent apart from the narratives (their grounding never drops it) and again on a retry; no follow or decision model is needed.
2. Render the storylines (focus marked) and the flagged trends once for the step. For each of the step's buckets, under that bucket's lock and the global author limit: if a narrative for this step already exists, publish it again; otherwise build the author variables at the step's horizon, call the author, save the narrative with the next `seq`, then publish it.
3. Remove the step from `pending` and add its ref to `done`.

### 3.5 Identifiers

*In short: deterministic IDs make retries idempotent.*

| Thing | ID |
| --- | --- |
| Block | `block:{matchId}:{level}:{start}:{end}`; `tier` `minute`, `five-minute`, `twenty-minute` (earlier) or `half` (a closed period) |
| Step | `{matchId}:{ref}`, refs `key:{eventId}`, `scheduled:{minute}`, `halfTime:1`, `fullTime:2`, `catchUp:{bucket}:{revision}`, `turn:{storylineId}:{opens\|resolves}` |
| Analysis | `analysis:{matchId}:{minute}`, `…:halfTime:1`, `…:fullTime:2` (queued with ref `analysis:…`) |
| Storyline | `sl:{matchId}:{n}` |
| Narrative | `narr:{matchId}:{userType}:{seq}` |

## 4. Audience targets

*In short: the user backend decides which buckets exist and which are active (`audience/targets.py`).*

- `HttpTargetSource` reads `GET {USER_BACKEND_URL}/matches/{matchId}/audience-config` (ETag) with the run-scoped matchId; the backend resolves the fixture's audience template. It uses `generation_targets`: the buckets enabled in the backend's configuration (no viewer presence). Each target's layer and option descriptions become the author's audience text.
- Each queued step stores its targets and audience revision; narratives carry `audienceRevision`. An empty list: nothing is written. Never read (backend down): the step waits (`TargetsUnavailable`) and the worker retries.
- `framing(target, info)` builds the author's `{user_type}` text from each layer's and option's description plus the MA1 team names. It adds "This audience supports X" when an option has `team` (`home`/`away`), or else a `label` naming only `{home}` or `{away}`; layer and option ids carry no meaning.
- Tests and `devtools.local` only: `StaticTargets` (`tests/doubles/targets.py`) serves the original 12 buckets and `ShippedPrompts` (`narrative_engine/agents/prompt_source.py`) the shipped files. `Router` and `MatchOrchestrator` refuse to start without targets, so the service has no built-in buckets.
- Prompts: `agents/prompt_source.py` reads `GET {USER_BACKEND_URL}/narrative-prompts` (ETag) and accepts a template only if its placeholders equal the shipped file's; otherwise (or unreachable with nothing cached) `PromptUnavailable` pauses the work and `/health` is 503. `promptVersion` is `{role}@{version}` from the API or the file name (`narrative-author.v8`); a step pins its author prompt on the first attempt.
