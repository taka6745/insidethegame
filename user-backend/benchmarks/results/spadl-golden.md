# SPADL golden sets: before and after

> **In short:** on 21 October 2026 the question and replay golden sets moved to SPADL definitions. The local model now passes **25/25** questions (was 23/25) and **41/42** replays (was 34/40), with fewer tokens per question. Two question values and six replay values changed meaning; every change is listed below.

| | |
| --- | --- |
| **Recording** | Chelsea–United GRF (synthetic), SPADL actions from its MA3 stream via `etl/reference/spadl.py` |
| **Runner** | `benchmarks.question_inprocess`, `benchmarks.replay_eval` (in process; no API, database or stack) |
| **Model** | The local development model, one run each; results vary between runs |
| **Raw results** | [spadl/](spadl/) |

## 1. Scores

*In short: accuracy up on both sets; scripted doubles unchanged.*

| Set | Before (canonical events) | After (SPADL) |
| --- | --- | --- |
| Questions, local model | 23/25 (`united-cards-sent-off`, `keeper-saves` failed) | **25/25** |
| Questions, scripted | 23/23 | 23/23 |
| Replays, local model | 34/40 (20 Oct) | **41/42**, 0 hard failures |
| Replays, scripted double | 32/40 | 35/42 (the 7 misses are model-only phrasings the double does not script) |

The one replay miss (`last-five-minutes-off-target`) called two off-target shots "saved by Lammens": SPADL's `keeper_save` cannot tell a goalkeeper's touch on an off-target shot (Opta qualifier 190) from a real save, so that distinction is lost in conversion.

## 2. Context variants (A/B on the local model)

*In short: the full SPADL dictionary and the compact one score the same; the runtime keeps the full dictionary plus `lookup_spadl`.*

| Variant | Questions | Stat question tokens (median) | All questions (mean) |
| --- | --- | --- | --- |
| Before: canonical feed reference + measurement support | 23/25 | 31,864 | 41,717 |
| **Full SPADL dictionary in context + `lookup_spadl` (runtime)** | **25/25** | 28,559 | 28,765 |
| Compact: enum names only + `lookup_spadl` (`--reference compact`) | 25/25 | 26,783 | 27,742 |

Accuracy decided the choice; the tie keeps the definitions in context. Tokens are informational.

## 3. Changed question expectations

| Case | Before | After | Why |
| --- | --- | --- | --- |
| `keeper-saves` (Lammens) | 7 | **9** | SPADL `keeper_save` is every Opta save by him, including 2 touches of off-target shots (the catalogue's `saves` changed the same way) |
| `player-touches` (Palmer) | 242 | **73** | SPADL has no touch record; on-ball actions = every action type except `dribble` (carries are inferred) |

Every other case keeps its value under the SPADL definition: passes are the pass family (479, 291, 358/479 = 74.7%), shots the shot family (16, 8, Reece James 4), corners `corner_crossed`/`corner_short`, leaders by completed passes (Andrey Santos 109), shots (three-way tie on 4) and tackles. Cards and the sent-off answer come from MA3 card rows; scores from MA3 goals and VAR rows.

## 4. Changed replay expectations

| Case | Before | After | Why |
| --- | --- | --- | --- |
| `saves` | 9 | 12 | `keeper_save` includes off-target touches and blocks |
| `saves-lammens` | 7 | 9 | Same |
| `interceptions` (half-time + 120 s) | 15 | 52 | SPADL interception includes blocked passes; now a broad request that needs a refine offer |
| `interceptions-second-half` | 18 | 64 | Same |
| `big-chances` | 4 | 23 | No big-chance flag; proxy is shot-type actions starting in `opp_box` |
| `broad-touches` | 8,713 | 1,852 | No touch record; every action except carries |

Same counts under new definitions: goals (shot types with result success, plus own goals), shots on target (`shot_outcomes` goal or saved), headers (`bodyparts` head), corners, offsides (pass types with result offside), cards (MA3 rows), tackles won, fouls, team and player shots.

## 5. Agent corpora

*In short: the 100-intent corpus and its cohorts are translated, not re-authored.*

Gold rules are translated to SPADL with the saved-rule migration's vocabulary map ([spadl_corpus.py](../spadl_corpus.py)). Intents SPADL cannot express (cards, touches) become expected refusals or catalogue reuse; controls that SPADL now answers (touches inside the box) were replaced by aerial duels. Five pass-count intents gained their taken corners, which SPADL counts as passes. Gold checks: baseline 88/88, quality 99/99, balanced 84/84, transfer 10/10, data-transfer 14/14. The agent cohorts were not re-run on the model.
