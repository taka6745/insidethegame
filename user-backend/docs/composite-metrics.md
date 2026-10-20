# Composite metrics

**Implemented:** percentages, dimensionless ratios, differences and recorded-distance averages, using Microsoft Agent Framework's typed goal workflow and deterministic compilation. Standard statistics still come from ETL; custom calculations only fill missing scopes.

```text
Question → reuse ETL metric, clarify, or compile a custom definition
                                           ↓
Event → shared filter index → aggregate inputs → formula → pinned card
```

| Operation | Meaning |
| --- | --- |
| Percentage | `100 × subset / population`; compatible units and provable filter containment |
| Ratio | `left / right`; compatible units, no clamping |
| Difference | `left − right`; compatible units |
| Average | Recorded distance sum / count of present distances; includes zero, excludes missing values |

A formula has exactly two count/sum inputs; average compiles its own sum and count-present pair. Inputs cannot themselves be formulas. Percentage and ratio with zero denominators return `null`, displayed as unavailable, and can still be tracked. A percentage numerator must preserve all denominator restrictions. The bounded containment check recognises identical predicates and narrower categorical membership; unsupported equivalence is rejected, not guessed.

**Example:** Chelsea pass completion since 60′ counts successful passes over passes with resolved success/failure outcomes. Both inputs use Chelsea, pass, and `time >= 3600`. Unknown outcomes are excluded. An ETL whole-match pass-accuracy metric must be reused when it matches the request.

## Shared work and recovery

Leaf IDs preserve the previous count/sum identity. Formula IDs include a versioned operation and ordered leaf IDs; wording and viewer identity are excluded. Equivalent formulas share one result; overlapping formulas share aggregate inputs. Input counters remain hidden unless independently requested.

Each event first applies all leaf deltas, including corrections/retractions, then recomputes only dependent formulas once. Only changed public values advance delivery versions. Duplicate revisions do no work. Definitions and results use the existing PostgreSQL JSON storage; result updates commit with the replay cursor. Restart rebuilds dependency indexes from retained definitions and observed history, then restores delivery versions. No model runs in the event path.

The demo remains one process owning one match. Untracking removes a viewer's pin; definitions remain reusable until match reset. `FILTER_MAX_CALCULATIONS` caps distinct activated public calculations per match (default 10,000; range 1–1,000,000). Each formula adds at most two shared leaf counters. At the limit, equivalent existing metrics can still be tracked; new activation fails before history backfill or persistence. This is not distributed worker ownership or reference-counted eviction. Production activation/outbox, owner fencing and bounded history backfill remain separate work.

## Agent and chat contract

The model selects reuse, a validated goal, clarification or unsupported. Composite goals contain two independently scoped aggregate inputs; averages use `operation=average` and `sum_field=distance_metres`. Catalogue entity IDs, feed capabilities, units and time limits are validated. No generated Python, SQL or expression evaluation runs in the API.

Clarification replies carry `{question, options, allow_free_text}`. Options are validated model choices, at most five; free text is enabled by default. They survive saved chat and reconnect. The next reply is interpreted with the prior question and full validated goal, preserving team/player/time constraints. No result or tracking offer is created while meaning is unresolved.

Not supported: rolling windows, arbitrary formulas, sequences, joins, spatial duration from sparse event locations, or averages of already-computed percentages. Missing feed channels remain unavailable rather than zero.

Tests: `tests/test_composite_metrics.py` contains independent ledger expectations; `tests/test_composite_api.py` checks actual PostgreSQL/API persistence, Track, live updates, shared viewer state and clarification continuity.

## Local verification — 20 October 2026

The full backend suite passed 548 tests; the frontend passed 108 tests and its production build. Final capacity/cache changes also passed focused tests and independent review. Browser checks confirmed a custom percentage answer, Track, live value changes, and a suggested clarification reply preserving its team. The free-text action focuses the existing composer; API tests cover free-text continuation.

The local model compiled percentage, average and difference smoke requests in roughly 5–7 seconds. An earlier full-viewer attempt timed out; these checks do not establish general model reliability or a response-time guarantee.

The opt-in `benchmarks/composite_perf.py` measured 10,000 formulas over 100 events: selective scopes took 0.093 ms median / 0.166 ms p95 per event; a shared denominator affecting all formulas took 23.4 ms / 33.0 ms. These are local CPU measurements, excluding networking and viewer delivery. Cost follows affected dependencies, not simply viewer count.
