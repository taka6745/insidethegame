# Filter checks, outside pytest

```text
100 hand-authored cases ──→ independent event/revision answers
         │                           ↑ compare every delivery
         └─ prompt → framework agents → generated rule → filter engine

14,018 GRF deliveries → generated unique rules → timed engine.ingest
                                            → 1 / 5 / 100 events/s queue model
```

```sh
./dev benchmark filters  # no model, database or network connections
./dev benchmark values  # cached per-person value reads; no delivery simulation
./dev benchmark agents  # explicitly calls your configured local development model
```

All commands use Docker and write ignored results to `.local/benchmarks/`. They do not change the lab, its recording or saved rules. Agent checks need the [local model configuration](../docs/local-llm.md). No automatic model fallback to fixture answers. Run before merging a model/prompt change, not in normal pytest or CI.

## Correctness

[cases.py](cases.py) contains **100 distinct hand-authored rules**, prompts and explicit per-event/revision contributions. Clear, casual and typo-heavy prompts target known answers. Another 12 deliberately ambiguous/unsupported prompts should be clarified or declined. Gold answers never come from the model or production predicate evaluator.

Every generated rule is checked against all **35 delivery prefixes**, late-registration backfill and normalized rule constraints. This catches deleted goals, player/body-part corrections, reassigned corners, duplicates, half boundaries and inclusive/exclusive minutes. A `different_constraints` failure means the fixture values matched but the rule differs from the expected contract; inspect it, since redundant team filters can be harmless on this match but change reuse identity. A status failure includes timeouts, not just semantic errors. The harness does not silently loosen expectations to pass the model.

Default agent limits: **4 concurrent cases, 60 seconds per case, 15 minutes overall**. Each case has an initial coding attempt plus `AGENT_MAX_REPAIRS` repairs (default 3). Results flush after each case; unfinished cases are marked unmeasured. Those limits protect the runner, not a claim that a match takes 15 minutes to process.

```sh
./dev benchmark agents --case-id stat-021 --case-timeout 90
./dev benchmark agents --limit 5 --concurrency 1
```

Without any model, validate the hand-authored rules and oracle:

```sh
PYTHONPATH=user-backend python -m benchmarks.correctness
PYTHONPATH=user-backend python -m benchmarks.full_match  # 100 generated rules vs full GRF history
```

## Performance

The generated rules use actual player/event/period combinations from the saved GRF match plus distinct integer time windows. No agent creates the bulk rules. These are distinct canonical rule IDs, not necessarily distinct results on this recording; many windows overlap and some upper bounds extend beyond the observed game. Two workloads expose different costs:

| Workload | What it measures |
| --- | --- |
| Selective | Player + event + half indexes narrow candidate sets; remaining time conditions are evaluated. |
| Overlapping | Time-only rules share the wildcard bucket; every event is a candidate for every rule. |

Sizes: **100, 1k, 10k, 100k, 1m, 10m, 100m**. Each size runs in a fresh subprocess. Defaults: 30-second build limit, 20-second replay limit, 1 GiB RSS ceiling and a 5-minute suite deadline. A parent watchdog kills hung/oversized workers. If a smaller tier reaches a limit, larger tiers are explicitly **unmeasured**, not extrapolated as successful. A replay limit produces timings for the measured prefix, with its event count and `full_match=false`; short prefixes may not represent the whole game. `--event-order spread` uses a fixed-seed permutation spanning the recording; it requires unique event IDs and is only for performance sampling, not chronological or correction-feed validation.

`ingest` timing includes candidate lookup, predicate evaluation, correction bookkeeping and changed-result construction. Excludes generation, parsing, DB, model calls, JSON serialization and network delivery. Independent scalar checks compare four sampled rules against the replayed prefix at every tier. The **1/5/100 events/s** rows are a deterministic queue simulation using measured service times, not sleeping or real traffic. Throughput is an average, not a latency guarantee.

The shared-viewer table assumes **100 distinct filters shared by 100k–100m viewers**. Compute is identical under that assumption; it allocates no viewer records and claims nothing about routing or delivery. The separate value-read benchmark exercises cached values across 100k stored IDs.

```sh
./dev benchmark filters --sizes 100 1000 10000 100000 --replay-timeout 60
./dev benchmark filters --memory-mb 2048 --build-timeout 60 --suite-timeout 600
./dev benchmark filters --sizes 100000 --event-order spread  # seeded whole-match sampling
```

The model evaluation measures understanding; this benchmark measures the existing algorithm. Neither is a production capacity guarantee. [Measured results](results/README.md).

Render a shareable Markdown/SVG report from local results:

```sh
PYTHONPATH=user-backend python -m benchmarks.report --agents .local/benchmarks/agents/report.json
```

## Agent interpretation and clarification

The original 112-case corpus and its recorded result stay unchanged. Run both
cohorts when comparing an agent change:

```sh
./dev benchmark agents --cohort baseline
./dev benchmark agents --cohort quality
```

`quality` has 100 readable viewer requests covering the same independent gold
rules, the 12 original negative prompts, and 12 two-turn clarification cases.
Only after the model asks a question does the harness send the prewritten user
reply. Failing to clarify an ambiguous request is a failure even if a guess would
happen to give the right answer. Expected rules and revision weights never enter
agent prompts. Mixed-quality original wording remains in `baseline`.

Reports include each turn's status/latency, model-call counts, returned goal and
rule, and goal/compilation timings. Timed-out call counts are unknown, not zero.
A whole-match gold trace checks every event prefix; exact rule identity catches
constraints that accidentally match this fixture. **Compiler validation proves
that the rule preserves the interpreted goal; the independent gold evaluation
checks whether that interpretation matches the request.** Neither proves model
accuracy for unseen users. A clearer corpus is reported separately from a
same-corpus comparison; it cannot replace the original score.
