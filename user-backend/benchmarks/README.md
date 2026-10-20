# Filter checks, outside pytest

The separate [question conversation check](question_cases.json) has twelve fixed prompts on the shipped Chelsea–United recording: standard stats, possession split, custom/follow-up/percentage stats, clarification and its answer, match description, general football and two unavailable-data refusals that must name what is missing. `tests/test_question_cases.py` recomputes every expected value from the recording. Finish a **fresh full replay** in the lab, then run:

```sh
PYTHONPATH=user-backend python -m benchmarks.evaluate_questions --output .local/benchmarks/questions-unique-run-name.json
```

This explicitly calls the configured local model through the running API and takes over the Chelsea demo profile's chat session. Use a different profile in the browser. It never starts replay or clicks Track. Automatic checks cover status/source/known values; manually review every explanation and generated rule. Results are not a blanket accuracy score. The original 100-filter corpus below is unchanged.

20 October 2026, in-process against the local model (no API session): 12/12 on one run; 10/12 later on the local model, which asked a clarification for the follow-up and the clarification answer (the same with or without that day's router wording change). Under concurrent load, the 60 s plan timeout dominated failures.

Run it from the repository root with the backend Python environment activated (dependencies from `user-backend/requirements.txt`), and keep replay/Track unchanged during the check. Failed HTTP/model attempts remain in the output file. It also verifies that answering did not add live calculations.

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

The `./dev benchmark` commands use Docker and write ignored results to `.local/benchmarks/`. They do not change the lab, its recording or saved rules. Agent checks need the [local model configuration](../docs/local-llm.md). No automatic model fallback to fixture answers. Run before merging a model/prompt change, not in normal pytest or CI.

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
| Selective | Player + event + half indexes select predicate families, then the clock index selects matching windows. |
| Overlapping | Time-only rules share a predicate family; the clock index skips inactive windows. Every actually changed result still needs an update and output record. |

See [index invariants and actual complexity](../docs/filter-engine-design.md): 64 categorical probes are only lookup overhead, not the cost of processing all candidates or emitting and sorting changed results.

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

### Balanced wording and user feedback

```sh
./dev benchmark agents --cohort balanced --concurrency 2 --case-timeout 60 --suite-timeout 1200
PYTHONPATH=user-backend python -m benchmarks.check_conversation_runner
```

`balanced` matches **30 gold intents across clear, average and poor wording**
(90 stat requests) plus 10 unsupported controls. Each request has two prepared
natural user replies, sent only if the agent asks for clarification. Truly
ambiguous cases must ask first: a lucky guess does not pass. Replies never expose
expected values, fixture events or the filter DSL. There is no runtime tuning
based on this frozen cohort.

The report separates immediate correct stats, correct clarification decisions,
correct final results after feedback, unnecessary questions, unsafe guesses,
wrong values/constraints, timeouts and per-turn latency. Controls stay separate.
Cases and full transcripts are inspectable; old cohorts remain unchanged.

```sh
PYTHONPATH=user-backend python -m benchmarks.report_balanced --input .local/benchmarks/agents-balanced/report.json
```

[Measured balanced-cohort results](results/agents-balanced.md): matched wording bands, scripted feedback, complete traces and remaining misses.

### Compare pinned models and prompt variants

The standalone comparison uses the same Microsoft Agent Framework workflow and
independent oracle. Put routing configuration in an ignored file, for example
`.local/model-strength/models.json`:

```json
{"models":[{"label":"small","model":"requested-model-id","expected_models":["reported-model-id"]}]}
```

```sh
PYTHONPATH=user-backend python -m benchmarks.model_strength \
  --models-config .local/model-strength/models.json \
  --env-file .local/backend-llm.env --cohort balanced \
  --concurrency 2 --case-timeout 60 --suite-timeout 1200 \
  --output .local/benchmarks/model-strength
```

Use repeatable `--case-id` or `--limit` for screening. Select `--variants current`
for a confirmation run, retain baseline/current by default, or use
`--variants current schema` to compare prompt instructions with strict structured
output. Schema mode sends the generated contract in both the protocol and model
context and validates JSON types locally. It requires a compatible route and
never silently falls back to prompt mode. The observer records `response_format`,
`strict_requested` and the wire-schema hash; these prove what was requested, not
that the provider constrained decoding.
`--candidate-prompt path/to/frozen.txt` overrides only current instructions and
keeps the compact schema; it is read once at suite start, with its hash recorded.
This allows a saved candidate to be rerun after runtime instructions change. Models run sequentially;
within each case, baseline/current order alternates. The frozen
[prompt baseline](prompts/goal-baseline.txt) uses its [frozen original schema](prompts/goal-baseline.schema.json), while the
current variant uses the current instructions and compact schema. This compares
both changes together, not their individual effects. The timeout is **per user
turn**; at most two scripted clarification replies are allowed, with an overall
suite deadline.

Each call records requested/returned model names, elapsed time, HTTP status,
serialized request bytes, request/prompt/schema hashes and reported token counts.
If the response marks token usage as estimated, that flag is retained; missing
usage stays unknown. No local token estimates are invented. Reports retain
schema/transport failure reasons, retries, clarification outcomes and oracle
results. No endpoints, credentials, raw response bodies or headers are saved.

A missing model identity or unexpected substitution cannot count as a pinned
pass, even if the answer is correct. Deterministic responses that never call a
model are reported separately as unverified. Returned identity is self-reported,
not proof of which weights ran. `Cache-Control: no-cache` is requested, but a
server may ignore it. A single run measures this corpus under its observed load;
it is not a statistical ranking or a guarantee for unseen intents.

`report.json` and `results.jsonl` preserve every model/variant/case, and `README.md`
gives a short comparison. Ordinary pytest covers observer/runner mechanics with
mock HTTP responses; no live comparison runs in pytest.

`--cohort transfer` checks 12 additional gold intents that are absent from the
balanced cohort. Their new, explicit viewer requests cover first-half added time,
headed passes/shots, inclusive/exclusive windows, combined event types and pass
metres. Each has one short prepared reply, sent only after clarification. This is
unseen wording across additional **known** intents, not unseen football semantics
or an untouched test domain. Keep runtime prompts frozen during this check.

`--variants current skill` compares fixed feed mappings with the adapter's
[event-data skill](../docs/data-skill.md), with the same prompt-mode output schema.
Use `--variants schema schema_skill` for the equivalent structured-output pair.
Skill mode replaces the fixed metric-mapping instructions with the data reference;
it does not append benchmark examples or make another model call. Reports record
the reference/skill hash as well as the prompt and schema hashes.

`current skill_added` (or `schema schema_skill_added`) is the additive ablation:
original instructions and output schema are identical within each pair, and only
the data-skill context is added. This benchmark-only variant measures extra
knowledge separately from the reference replacement; the runtime does not keep
two independent data mappings enabled.

`--cohort data-transfer` uses 20 frozen, independently authored requests with
fictional player/team names and IDs. The fixture and gold rules are consistently
remapped before evaluation; event-revision weights stay unchanged. Four incomplete
requests must clarify; four unavailable-data requests must be unsupported. This is
a transfer check over a reused match and known capabilities, not a new-domain test.

Composite graph CPU check: `python benchmarks/composite_perf.py --formulas 10000 --events 100` (from `user-backend/`). Compares selective team scopes with a deliberately shared denominator that invalidates every formula. Reports measured registration, median/p95 event time and dependency evaluations; no viewer/socket capacity claim. Separate from pytest and LLM correctness checks.
