# Agent interpretation improvements

Measured with the configured local model through Microsoft Agent Framework. Original results and prompts remain unchanged.

| Cohort | Exact passes | Median request seconds | p95 request seconds |
| --- | ---: | ---: | ---: |
| Original recorded mixed-quality stat requests | 68/100 | 21.45 | 35.17 |
| Same 100 requests after improvements | 94/100 | 8.69 | 37.16 |
| Same 12 negative/ambiguous requests | 11/12 | 8.59 | 17.65 |
| Separate 100 quality requests | 96/100 | 8.47 | 34.14 |
| Quality cohort: original negatives | 12/12 | 9.18 | 17.27 |
| Two-turn clarification conversations | 10/12 | 18.20 | 26.52 |

Stat-request outcome breakdown:

| Run | Exact | Wrong values | Different constraints | Timeout | Other non-ready |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original recorded mixed-quality stat requests | 68 | 14 | 6 | 1 | 11 |
| Same 100 requests after improvements | 94 | 0 | 0 | 4 | 2 |
| Separate 100 quality requests | 96 | 0 | 0 | 4 | 0 |

## What changed

- One model call defines the semantic goal; a typed compiler maps it to a rule without another model call.
- The goal schema enumerates available event types and outcomes. Feed semantics distinguish headed contacts, shots/goals, and clock boundaries.
- Ambiguous requests can ask a question and interpret the subsequent user reply with bounded conversation history.
- All ready rules are checked against independently hand-authored event/revision weights and exact constraints. Gold answers never enter model prompts.

## Limits

These are single evaluation runs, not statistical accuracy guarantees. The two updated cohorts ran concurrently (four cases each), sharing a model service. Their latency includes that load and cannot establish an isolated before/after speedup. Each turn had a 45-second deadline; a two-turn conversation can take up to twice that. The quality cohort changes wording, so its score is separate from the same-corpus comparison.

Compiler validation proves preservation of the interpreted goal; it cannot prove that the goal reflects user intent. A clear description is returned for review. The deterministic engine remains independent of the model.

Timeout call counts are unknown; the exporter corrects the initial instrumentation default zero to null when no stage completed. No network/viewer-delivery performance claims are made by this agent evaluation.

## Remaining failures

- Mixed-quality `stat-005`: status (failed).
- Mixed-quality `stat-012`: status (failed).
- Mixed-quality `stat-015`: status (failed).
- Mixed-quality `stat-016`: status (failed).
- Mixed-quality `stat-057`: status (clarification).
- Mixed-quality `stat-055`: status (clarification).
- Mixed-quality `negative-06`: status (clarification).
- Quality/conversation `quality-stat-078`: status (failed).
- Quality/conversation `quality-stat-080`: status (failed).
- Quality/conversation `quality-stat-083`: status (failed).
- Quality/conversation `quality-stat-086`: status (failed).
- Quality/conversation `conversation-08`: missed_clarification (failed).
- Quality/conversation `conversation-07`: wrong_event_value (ready).

## Focused clarification recheck

After adding an unresolved-player-reference guard and strengthening carry-forward instructions: **12/12** exact conversations; median 15.61s, p95 27.83s. This 12-case rerun is separate from the original conversation result above; it does not overwrite the lost-constraint failure.

The guard asks which player before calling the model when the first request has an unresolved possessive reference. It does not guess or rewrite metric constraints. Follow-up semantics remain model-interpreted, not guaranteed.

[Focused conversation results](agents-conversations-final.json)

## Serial timing smoke

Three requests/conversations after the full suites finished, concurrency 1. This tiny sample is a latency observation, not an SLO or accuracy estimate.

| Case | Result | Total seconds | Model calls |
| --- | --- | ---: | ---: |
| quality-stat-021 | pass | 7.812 | 1 |
| quality-stat-059 | pass | 6.879 | 1 |
| conversation-07 | pass | 32.957 | 3 |

[Serial raw results](agents-serial-smoke.json)

[Original results](README.md) · [Updated mixed-quality raw results](agents-improved-baseline.json) · [Updated quality/conversation raw results](agents-improved-quality.json)
