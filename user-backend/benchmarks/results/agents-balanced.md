# Balanced prompt-quality evaluation

Measured 18 October 2026.

**30 distinct stat intents × 3 wordings = 90 stat requests, plus 10 unsupported controls.** Each intent has the same independent event/revision gold answer across its clear, average and poor wording. Runtime semantics had already been developed against this original intent family: this is a wording/clarification stress cohort, not a fully held-out new-intent generalisation test. This controls calculation complexity when comparing prompt quality; these are not 90 independent football scenarios. The oracle uses the existing synthetic Opta-inspired fixture: 35 event deliveries, including corrections and deletions. Each ready rule is checked at every delivery, on historical backfill, and for exact filter constraints.

**Final correct stat requests: 88/90. Unsupported controls: 10/10.**

| Wording | Correct first decision | Correct stat on first turn | Correct after feedback | Median total seconds |
| --- | ---: | ---: | ---: | ---: |
| Clear | 30/30 | 30/30 | 30/30 | 8.34 |
| Average | 30/30 | 30/30 | 30/30 | 9.06 |
| Poor | 28/30 | 14/30 | 28/30 | 9.58 |

“Correct first decision” counts asking a necessary clarification as correct. “Correct stat on first turn” requires an immediately correct rule and disallows guessing missing information. Final correctness requires the correct rule **and** any required initial clarification; a lucky guess does not pass.

## Feedback and failures

| Wording | Cases needing clarification | Questions asked | Unnecessary questions | Missed required clarification | Wrong ready values | Wrong constraints | Timeouts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Clear | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Average | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Poor | 16 | 14 | 0 | 2 | 2 | 0 | 0 |
| Control | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

16 poor prompts deliberately omit an entity, metric or time detail. The remaining poor prompts use typos/shorthand while retaining the intended information. A prepared complete natural-language restatement supplies the intended request **only after the agent asks**. A second complete restatement is available if it asks again; then the case stops. This tests recovery with informative user feedback, not the harder case of terse slot-only replies (covered separately in the earlier conversation cohort). Clarification-question relevance is not independently graded here. No answer includes expected numeric results or filter DSL.

Unsupported controls were correctly rejected initially in 10/10 cases and finally in 10/10. Falsely accepted controls: 0. Their replies preserve the unsupported request rather than changing it to an easier supported metric.

Failures and question counts overlap; they are diagnostic measures, not mutually exclusive categories. A failed request before answering a required question is recorded as a missed clarification, but only a ready/reuse response is an unsafe guess.

## Latency and method

The frozen run used concurrency **2**, a **60s** deadline per turn and **1200s** for the suite. No semantic tuning or prompt rewrites were made during this run. Each case starts a fresh request; it can use up to two scripted replies (three turns total). Model context contains only the match/team/player catalogue and an empty standard-stat catalogue, isolating custom-filter interpretation rather than ETL stat reuse. Replies preserve the complete user history and the same numbered assistant options as the application.

| Wording | Median first turn seconds | p95 first turn seconds | p95 total seconds | Mean turns |
| --- | ---: | ---: | ---: | ---: |
| Clear | 8.34 | 17.74 | 17.74 | 1.00 |
| Average | 9.06 | 12.22 | 12.22 | 1.00 |
| Poor | 6.78 | 14.31 | 23.05 | 1.47 |
| Control | 9.30 | 15.83 | 15.83 | 1.00 |

Suite-timeout/unmeasured cases: **0**. Latency excludes human thinking time; scripted replies arrive immediately. p95 uses the nearest-rank method. Model-call counts are null when a timeout leaves them unknown. Typed compilation is verified, while semantic understanding is evaluated rather than guaranteed. This single local-model run is not a production accuracy or capacity claim.

## Cases that did not pass

| Case / request | First → final status | Result |
| --- | --- | --- |
| balanced-10-poor: corners in that second | ready → ready | missed_clarification |
| Model interpretation | Count of corners in the second half | Clarification was required |
| balanced-15-poor: track passing for both sides | ready → ready | missed_clarification |
| Model interpretation | Count all pass events for both teams in the match | Clarification was required |

[Exact prompts, prepared replies and gold cases](agents-balanced-cases.json) · [All per-turn results](agents-balanced.json) · [Earlier agent comparison](agents-improved.md)
