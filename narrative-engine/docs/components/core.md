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
| `PeriodChanged` | ETL `PeriodStarted` / `PeriodEnded` | `periodId`, `started`, and the Start/End event's `clock`, `timeSec` when the body has them |
`parse_notification(body, messageType)` switches on `messageType` and returns `None` for any other type before reading a field (the topic is shared). Every ETL body carries every key, unused ones `null`.

Buckets are not messages: the orchestrator reads the user backend's current targets ([audience](#4-audience-targets)).

### 1.3 Records

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
| Any (and the router's 5 s poll) | Targets re-read; on a new revision a `catchUp` step for each newly enabled bucket; a disabled bucket gets no further steps |
| `PeriodChanged` (end) | The period's end and its last minute are closed at the End event's clock (from the body, else the ETL) |

### 3.3 The work loop

Under a per-match lock, repeat until nothing is due:

1. If a queued step is ready (its gate minute is summarised), run the one with the earliest horizon; at equal horizons a match analysis runs first, so the steps there read it.
2. Else, if a closed minute is unsummarised, summarise it (empty minutes, and merges of only empty minutes, need no model call), compress, queue a match analysis at minutes 5', 10', 15' …, and queue a `scheduled` step if ten minutes have passed without one. A period's last minute skips both (closing the period merges it and queues the half-time or full-time step); stoppage time queues no `scheduled` step.
3. Else, if a period has ended, collapse its blocks and queue its analysis and then `halfTime` or `fullTime`. `PeriodEnded` closes the period's last minute at once, at the End event's clock and second (no wait for `MinuteClosed` or the ETL's idle flush). That minute is summarised only once its End row is in ETL GraphQL (`EtlBehind` until then).

The background worker retries failures with backoff doubling from 5 s up to 120 s. Waiting for the backend (targets, prompts) or the ETL logs a warning, not a stack trace. Work resumes after a restart because the queue is in the checkpoint.

### 3.4 Running a step

1. Rebuild the trigger reason (for key events from the stored row and match info). On the first attempt, pin the author prompt, the seq, the latest analysis and the focus storyline (§5).
   For a key event whose `keyType` is in the served `clips.key_types`, with `clips.enabled` and `clips.shared`, `_publish_moment_clip` first sends one `MomentClip` for the step's buckets (PLAN.md §10.2 D7; [contract](../../contracts/README.md#key-event-clips-type-momentclip)). It is sent apart from the narratives (their grounding never drops it) and again on a retry; no follow or decision model is needed.
2. Render the storylines (focus marked) and the flagged trends once for the step. For each of the step's buckets, under that bucket's lock and the global author limit: if a narrative for this step already exists, publish it again; otherwise build the author variables at the step's horizon, call the author, save the narrative with the next `seq`, then publish it.
3. Remove the step from `pending` and add its ref to `done`.

### 3.5 Identifiers

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
- Tests and `devtools.local` only: `devtools/targets.py` `StaticTargets` serves Luke's original 12 buckets and `ShippedPrompts` the shipped files. `Router` and `MatchOrchestrator` refuse to start without targets, so the service has no built-in buckets.
- Prompts: `agents/prompt_source.py` reads `GET {USER_BACKEND_URL}/narrative-prompts` (ETag) and accepts a template only if its placeholders equal the shipped file's; otherwise (or unreachable with nothing cached) `PromptUnavailable` pauses the work and `/health` is 503. `promptVersion` is `{role}@{version}` from the API or the file name (`narrative-author.v6`); a step pins its author prompt on the first attempt.

## 5. Analysis and storylines (`analysis/`)

*In short: a neutral analyst names what is developing, citing the ETL's trend numbers; a validator keeps only grounded observations; a pure reducer keeps the storylines; each author step advances one focus storyline.*

| | |
| --- | --- |
| **Code** | [`analysis/validator.py`](../../narrative_engine/analysis/validator.py), [`analysis/storylines.py`](../../narrative_engine/analysis/storylines.py), [`analysis/policy.py`](../../narrative_engine/analysis/policy.py); run by the orchestrator |
| **Policy** | Every tunable below (limits, caps, tolerances, lifecycle counts, salience weights, focus rotation, repair turns, claim questions and thresholds) is the user backend's `storyline-policy` (`GET /storyline-policy`, ETag; edited under `/dev/config/storyline-policy`; defaults seeded by its migration `026`, `030` adding the `comparison` claim and the `analyst` flags, `033` rewording `comparison`, `036` adding the `score` claim and `storylines.reopen_within`, shown here). No fallback: unavailable pauses the work and `/health` is 503. Code keeps only invariants: the reply schema, the language checks (xG, per-90) and the trend windows' minute marks |
| **Reads** | `executeTrendsAtSeq`, `executeTrendSpellsAtSeq` at the analysis's seq ([local contracts §4b](../../../local/contracts.md)); enabled trends only |
| **Writes** | Cosmos `analyses` (immutable snapshot each) and `storylines` (current state); narratives' `analysisId`, `storylineIds` |
| **Prompts** | `match-analyst` v4 (inputs and reply schema, its limits filled from the policy by `prompt_limits`; labels and headlines in plain football words from the indicators' meanings; resolved storylines shown without ids; no pattern list, no rules beyond the schema); `narrative-author` v5 added `{storylines}`, `{match_trends}`, v6 the trend units |
| **Tests** | `test_storylines.py`, `test_storylines_run.py` (whole Chelsea–United match: backlog = live, focus after 10', all resolved at full time, purge) |

### 5.1 The analyst and the validator

The analyst reads the trend table (per window — last 5, last 15, half, match — one line per indicator with both teams side by side; level and change flags), spells, the ledger, the context blocks and the storylines, and replies `{"observations": [{label, team, headline, explanation, confidence, evidence: [{indicator, team, window, value}], storyline}], "resolve": [{storyline, outcome}]}` in its own words. `validate` never checks a pattern; it keeps an observation only if:

- every cited value equals a served row (an enabled trend row, within `value_tolerance` 0.011 or `relative_tolerance` 1%, or a ledger fact: `goals`, `red_cards`, window `match`) and an observation about a team cites that team;
- confidence is a level (`confidence_levels`: `low` 0.4, `medium` 0.6, `high` 0.8; v1's numbers still accepted) at most `confidence_cap_short` 0.6 when all its rows are in `short_windows` (`last5`), else `confidence_cap_long` 0.9;
- its text uses only numbers from its evidence (or counts up to `small_counts_up_to` 3 and minutes up to the clock), names only teams in its evidence and players in the ledger, has no xG and no per-90 rate;
- its storyline move names an open storyline (once per analysis);
- the decision model finds no unsupported claim of a kind marked `analyst` in the policy's `claims` (seed: `result`, `comparison`, `intent`), asked of its label (it names the storyline), headline and explanation (a resolve: its outcome) with the analyst's own inputs as the evidence ([5.3](#53-the-authors-grounding-check)). An item that passed is not asked again after the repair turn.

Failing items get `analyst_turns` (1) repair turns: the analyst is shown each with its reasons and replies with corrected versions only (at most one per failure), which are validated again together with the items that passed, so the move and resolve limits hold across both. What still fails is kept with its reasons in `rejected`; `retried` lists the first-pass failures. Neither check is loosened by the repair. With no trend rows and nothing open, no model call is made. An analysis is written once; a retry reuses it.

### 5.2 Storylines

| Event | Effect |
| --- | --- |
| `open` | `sl:{matchId}:{n}` with the model's label and team; an open storyline with the same label develops instead |
| Develop | A beat with the cited rows; salience = confidence + `beat_weight` 0.1 × beats (up to `beats_counted` 5) |
| No development | Salience × `quiet_fade` 0.8; dormant after `dormant_after` 2 analyses, resolved ("Closed: no later analysis developed it", not a claim that the trend faded) after `resolve_after` 4 |
| `resolve`, full time | Resolved with the model's outcome (full time: else the score) |
| Key events | Goals, VAR, red cards and penalties since the last check that concern its team are linked by rule, each adding `key_event_boost` (goal, own goal, VAR 0.5; red card 0.4; penalties 0.3) |
| Cap | At most `max_active` 4 active, by salience |

**Focus** (`choose_focus`), pinned with the step and shared by its buckets: a `storylineTurn`'s own storyline; at full time one the final analysis resolved; for a key event the most salient storyline of the event's team; otherwise the most salient active storyline, less `focus_repeat_penalty` 0.25 per appearance in the last `focus_recent_steps` 3 steps (the checkpoint's `focusLog` keeps that many). Prompts show each storyline's latest `beats_shown` beats; authors also see storylines resolved in the last `resolved_shown_minutes` (Opta minutes, so across half time) and the whole-match `author_match_indicators` trends, flagged or not (backend migration 031). Each storyline records `salienceHistory` (its salience after every analysis that changed it), so readers bounded to a clock never see a later value. A work item retried after a failed claim check reuses its writing-model drafts (`_drafted`). An observation whose label matches a storyline resolved within `reopen_within` minutes reopens it (the earlier resolution kept in `resolutions`) instead of opening a second one. **Turns:** a scheduled analysis that opens or resolves a storyline queues one `storylineTurn` step for the most salient of them.

### 5.3 The author's grounding check

*In short: an excerpt may use only numbers and names its author was shown, and may not make a claim (a cause, an intent, the result, a comparison) the evidence does not support.*

`narrative_reasons` checks every author excerpt against what that author was shown: each number (digits, or a number word from two to twenty) must appear in the statistics, trends, storylines, ledger, events or trigger (rounded, or a share as a percentage), or be a small count or a minute up to the clock; each capitalised word after a sentence's first must be in the roster, the team names (with MA1 `shortName` and `knownNames`, e.g. "the Blues") or the inputs; no xG or per-90 rate. Then `claim_reasons_many` asks the decision model ([decisions](decisions.md), Microsoft-Decision-1), for each sentence of every draft in the step at once (quoted with the sentence before it, so "they" or "it" keeps its team), two bounded questions per claim kind in the policy's `claims` (`causal`: does it claim one thing caused another, and do the storyline beats, ledger, trends or trigger state that link; `intent`: does it say someone acted deliberately, and does the data show it; `result`: does it state or imply how the match ended, and does the evidence show it has ended; `comparison`: does it compare the teams, or a team with itself earlier (a single value called high or low is not a comparison), and do the numbers, read with what each measures, or a storyline beat or recap show that direction); a sentence fails when P(claim) ≥ `min_claim_probability` (0.5) and P(support) < `min_support_probability` (0.5). No claim kind uses a phrase list. The evidence state (`claim_state`) is every factual input the author saw: storylines with beats, ledger, trends, statistics table, minute recaps, latest events and trigger, so a comparison read off the statistics is checked against them. A failing excerpt gets `author_rewrites` (1) rewrites with the reasons; if they fail too, `repair.author_trim` (seed true, migration 035) removes only the sentences whose claims still fail, then checks the trimmed text again as a whole (a kept sentence now follows a different one); it is written if that passes (logged as removed); otherwise, or with it false, the bucket's excerpt for the step is dropped and logged.

