# Analysis

> **In short:** a neutral analyst names what is developing, citing the ETL's trend numbers; a validator keeps only grounded observations; a pure reducer keeps the storylines; each author step advances one focus storyline.

| | |
| --- | --- |
| **Status** | Implemented · tested |
| **Code** | [`analysis/validator.py`](../../narrative_engine/analysis/validator.py), [`analysis/storylines.py`](../../narrative_engine/analysis/storylines.py), [`analysis/policy.py`](../../narrative_engine/analysis/policy.py); run by the orchestrator |
| **Policy** | Every tunable below (limits, caps, tolerances, lifecycle counts, salience weights, focus rotation, repair turns, claim questions and thresholds) is the user backend's `storyline-policy` (`GET /storyline-policy`, ETag; edited under `/dev/config/storyline-policy`; defaults seeded by its migration `026` and updated by `027`–`036`, e.g. `030` adding the `comparison` claim and the `analyst` flags, `036` the `score` claim and `storylines.reopen_within`; shown here). No fallback: unavailable pauses the work and `/health` is 503. Code keeps only invariants: the reply schema, the language checks (xG, per-90) and the trend windows' minute marks |
| **Reads** | `executeTrendsAtSeq`, `executeTrendSpellsAtSeq` at the analysis's seq ([local contracts §4b](../../../local/contracts/README.md#4b-trend-definitions)); enabled trends only |
| **Writes** | Cosmos `analyses` (immutable snapshot each) and `storylines` (current state); narratives' `analysisId`, `storylineIds` |
| **Prompts** | `match-analyst` v4 (inputs and reply schema, its limits filled from the policy by `prompt_limits`; labels and headlines in plain football words from the indicators' meanings; resolved storylines shown without ids; no pattern list, no rules beyond the schema); `narrative-author` v5 added `{storylines}`, `{match_trends}`, v6 the trend units (v7 is current) |
| **Tests** | `test_storylines.py`, `test_storylines_run.py` (whole Riverton Rovers–Forgeham United match: backlog = live, focus after 10', all resolved at full time, purge) |

## 1. The analyst and the validator

*In short: the analyst replies in its own words; only grounded observations are kept.*

The analyst reads the trend table (per window — last 5, last 15, half, match — one line per indicator with both teams side by side; level and change flags), spells, the ledger, the context blocks and the storylines, and replies `{"observations": [{label, team, headline, explanation, confidence, evidence: [{indicator, team, window, value}], storyline}], "resolve": [{storyline, outcome}]}` in its own words. `validate` never checks a pattern; it keeps an observation only if:

- every cited value equals a served row (an enabled trend row, within `value_tolerance` 0.011 or `relative_tolerance` 1%, or a ledger fact: `goals`, `red_cards`, window `match`) and an observation about a team cites that team;
- confidence is a level (`confidence_levels`: `low` 0.4, `medium` 0.6, `high` 0.8; v1's numbers still accepted) at most `confidence_cap_short` 0.6 when all its rows are in `short_windows` (`last5`), else `confidence_cap_long` 0.9;
- its text uses only numbers from its evidence (or counts up to `small_counts_up_to` 3 and minutes up to the clock), names only teams in its evidence and players in the ledger, has no xG and no per-90 rate;
- its storyline move names an open storyline (once per analysis);
- the decision model finds no unsupported claim of a kind marked `analyst` in the policy's `claims` (seed: `result`, `comparison`, `intent`, `score`), asked of its label (it names the storyline), headline and explanation (a resolve: its outcome) with the analyst's own inputs as the evidence ([§3](#3-the-authors-grounding-check)). An item that passed is not asked again after the repair turn.

Failing items get `analyst_turns` (1) repair turns: the analyst is shown each with its reasons and replies with corrected versions only (at most one per failure), which are validated again together with the items that passed, so the move and resolve limits hold across both. What still fails is kept with its reasons in `rejected`; `retried` lists the first-pass failures. Neither check is loosened by the repair. With no trend rows and nothing open, no model call is made. An analysis is written once; a retry reuses it.

## 2. Storylines

*In short: a pure reducer opens, develops, fades and resolves storylines; one focus storyline per step.*

| Event | Effect |
| --- | --- |
| `open` | `sl:{matchId}:{n}` with the model's label and team; an open storyline with the same label develops instead |
| Develop | A beat with the cited rows; salience = confidence + `beat_weight` 0.1 × beats (up to `beats_counted` 5) |
| No development | Salience × `quiet_fade` 0.8; dormant after `dormant_after` 2 analyses, resolved ("Closed: no later analysis developed it", not a claim that the trend faded) after `resolve_after` 4 |
| `resolve`, full time | Resolved with the model's outcome (full time: else the score) |
| Key events | Goals, VAR, red cards and penalties since the last check that concern its team are linked by rule, each adding `key_event_boost` (goal, own goal, VAR 0.5; red card 0.4; penalties 0.3) |
| Cap | At most `max_active` 4 active, by salience |

**Focus** (`choose_focus`), pinned with the step and shared by its buckets: a `storylineTurn`'s own storyline; at full time one the final analysis resolved; for a key event the most salient storyline of the event's team; otherwise the most salient active storyline, less `focus_repeat_penalty` 0.25 per appearance in the last `focus_recent_steps` 3 steps (the checkpoint's `focusLog` keeps that many). Prompts show each storyline's latest `beats_shown` beats; authors also see storylines resolved in the last `resolved_shown_minutes` (Opta minutes, so across half time) and the whole-match `author_match_indicators` trends, flagged or not (a policy setting). Each storyline records `salienceHistory` (its salience after every analysis that changed it), so readers bounded to a clock never see a later value. A work item retried after a failed claim check reuses its writing-model drafts (`_drafted`). An observation whose label matches a storyline resolved within `reopen_within` minutes reopens it (the earlier resolution kept in `resolutions`) instead of opening a second one. **Turns:** a scheduled analysis that opens or resolves a storyline queues one `storylineTurn` step for the most salient of them.

## 3. The author's grounding check

*In short: an excerpt may use only numbers and names its author was shown, and may not make a claim (a cause, an intent, the result, a comparison, a score) the evidence does not support.*

`narrative_reasons` checks every author excerpt against what that author was shown: each number (digits, or a number word from two to twenty) must appear in the statistics, trends, storylines, ledger, events or trigger (rounded, or a share as a percentage), or be a small count or a minute up to the clock; each capitalised word after a sentence's first must be in the roster, the team names (with MA1 `shortName` and `knownNames`, e.g. "the Blues") or the inputs; no xG or per-90 rate. Then `claim_reasons_many` asks the decision model ([decisions](decisions.md), Microsoft-Decision-1), for each sentence of every draft in the step at once (quoted with the sentence before it, so "they" or "it" keeps its team), two bounded questions per claim kind in the policy's `claims` (`causal`: does it claim one thing caused another, and do the storyline beats, ledger, trends or trigger state that link; `intent`: does it say someone acted deliberately, and does the data show it; `result`: does it state or imply how the match ended, and does the evidence show it has ended; `comparison`: does it compare the teams, or a team with itself earlier (a single value called high or low is not a comparison), and do the numbers, read with what each measures, or a storyline beat or recap show that direction; `score`: does it state a score or what a goal did to it, and does the ledger show it); a sentence fails when P(claim) ≥ `min_claim_probability` (0.5) and P(support) < `min_support_probability` (0.5). No claim kind uses a phrase list. The evidence state (`claim_state`) is every factual input the author saw: storylines with beats, ledger, trends, statistics table, minute recaps, latest events and trigger, so a comparison read off the statistics is checked against them. A failing excerpt gets `author_rewrites` (1) rewrites with the reasons; if they fail too, `repair.author_trim` (seed true, migration 035) removes only the sentences whose claims still fail, then checks the trimmed text again as a whole (a kept sentence now follows a different one); it is written if that passes (logged as removed); otherwise, or with it false, the bucket's excerpt for the step is dropped and logged.

## 4. Grounding evidence

*In short: why every excerpt gets one repair turn.*

A live sample passed 61% of observations, and an author quoted a possession figure nobody served. The checks stayed; the analyst's confidence became a level, its trend table shows both teams per line, and a mismatch says what the table has. Local model, kickoff to 18′: 80% first pass, 100% after repair (15 observations); to 34′ before the table fix: 57% / 71%.
