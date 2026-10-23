# Benchmarks

> **In short:** opt-in evidence outside the runtime and outside pytest: the question and replay golden sets, the 100-case custom-stat corpus with its wording cohorts, model and prompt comparisons, and filter-engine performance tiers. Results go to ignored `.local/benchmarks/`; the frozen evidence from earlier runs is the JSON under `benchmarks/results/`, summarised in §5.

| | |
| --- | --- |
| **Code** | [`benchmarks/`](../../benchmarks/) (doubles in [`benchmarks/doubles/`](../../benchmarks/doubles/)) |
| **In pytest** | `test_question_golden.py`, `test_replay_golden.py` (scripted decisions), runner mechanics with mock HTTP; never a live model |
| **Output** | `.local/benchmarks/` (every generator's default); committed evidence in `benchmarks/results/*.json` |
| **Status** | Implemented; live-model figures are single development runs, not production accuracy or capacity claims |

## 1. Golden sets

*In short: the real agents with scripted or live model decisions, in process.*

| Set | Command (from `user-backend/`) |
| --- | --- |
| Questions (`question_cases.json`: 12 full-match + 13 timed prompts) | `python -m benchmarks.question_inprocess --agent fixture` (scripted) or `--env-file ../.local/backend-llm.env` (local model) |
| Replays (`replay_cases.json`) | `python -m benchmarks.replay_eval --agent fixture` or `--agent local`; `./dev benchmark replay` |
| Questions against a running stack | `PYTHONPATH=user-backend python -m benchmarks.evaluate_questions --match-id riverton-forgeham-XXXXXXXX` (repo root; a finished run; takes over the home analyst's chat, skips timed cases, never tracks) |

Snapshots are cut from the shipped Riverton Rovers–Forgeham United recording; SPADL actions come from its MA3 stream through ETL's converter (`etl/reference/spadl.py`, `finalSeq ≤ seq`) and standard stats from ETL's reference catalogue (`etl/reference/catalogue.py`), so no API, database or stack is needed. `tests/test_question_cases.py` recomputes every expected value from the recording. Scripted mode replays each case's recorded decision through the real agents, planner, compiler, rule engine and ETL-row answers. Replay cases also fail a caption that calls an unsaved shot saved; key-moment cases (`"recording": "archive"`) run against the archived recording with the narrative fixtures bound to it.

## 2. Custom-stat corpus and cohorts

*In short: hand-written gold, never from the model; clarification only when asked.*

```text
100 hand-authored cases ──→ event/revision weights → SPADL actions (spadl_corpus.py)
         │                           ↑ compare every delivery
         └─ prompt → framework agents → generated rule → filter engine
```

[`cases.py`](../../benchmarks/cases.py) holds 100 hand-authored rules with prompts and per-event/revision contributions, plus 12 ambiguous or unsupported prompts. Rules are translated to SPADL with the saved-rule vocabulary map; card intents expect a refusal or catalogue reuse; pass counts include the corners SPADL counts as passes. Every generated rule is checked at all 35 delivery prefixes, on late backfill and for exact constraints (`different_constraints` fails a rule that matches the values but not the contract).

| Cohort (`--cohort`) | Cases |
| --- | --- |
| `baseline` | The original 112 mixed-quality prompts |
| `quality` | 100 readable requests on the same gold, the 12 negatives, 12 two-turn clarifications |
| `balanced` | 30 intents × clear/average/poor wording + 10 unsupported controls; two prepared replies, sent only if the agent asks |
| `transfer` | 12 further known intents in new wording |
| `data-transfer` | 20 independently written requests with fictional names/ids; 4 must clarify, 4 are unavailable |

```sh
./dev benchmark agents --cohort balanced --concurrency 2 --case-timeout 60 --suite-timeout 1200
PYTHONPATH=user-backend python -m benchmarks.correctness   # gold rules and oracle, no model
PYTHONPATH=user-backend python -m benchmarks.report_balanced --input .local/benchmarks/agents-balanced/report.json
```

Defaults: 4 concurrent cases, 60 s per case, 15 min per suite, `AGENT_MAX_REPAIRS` repairs. Compiler validation proves the rule keeps the interpreted goal; the gold evaluation checks the interpretation.

## 3. Model and prompt comparisons

*In short: pinned models, frozen prompts, the same workflow and oracle.*

```sh
PYTHONPATH=user-backend python -m benchmarks.model_strength \
  --models-config .local/model-strength/models.json --env-file .local/backend-llm.env \
  --cohort balanced --concurrency 2 --case-timeout 60 --suite-timeout 1200
```

The models file (ignored) maps labels to requested and expected model ids. Results name models only by label. `--variants` compares `baseline`/`current` prompts, `schema` (strict structured output), `skill` (the [event-data skill](agents.md#4-spadl-vocabulary-for-agents) instead of fixed mappings) and `skill_added` (the skill added to unchanged instructions); `--candidate-prompt` reruns a frozen prompt. Each call records model label, latency, status, request bytes, prompt/schema hashes and reported tokens; no endpoints, keys or response bodies. A missing or unexpected model identity never counts as a pass. Frozen prompts live in [`benchmarks/prompts/`](../../benchmarks/prompts/).

## 4. Filter performance

*In short: the algorithm's cost, not viewer capacity.*

```sh
./dev benchmark filters   # 100 … 100m generated rules over Riverton Rovers–Forgeham United's SPADL actions
./dev benchmark values    # cached per-viewer value reads
PYTHONPATH=user-backend python -m benchmarks.full_match   # 100 generated rules vs independent totals
python benchmarks/composite_perf.py --formulas 10000 --events 100   # composite graph CPU
PYTHONPATH=user-backend python -m benchmarks.report --agents .local/benchmarks/agents/report.json
```

| Workload | Measures |
| --- | --- |
| Selective | Player + action + half indexes pick predicate families, then the clock index picks windows |
| Overlapping | Time-only rules share one family; every changed result still costs an update |

Each tier runs in a fresh subprocess with build, replay, memory and suite limits; a tier past a limit marks larger ones **unmeasured**, never extrapolated. `ingest` timing covers lookup, predicate evaluation and changed results, not parsing, database, model or delivery. The 1/5/100 events/s rows are a queue model from measured service times. Invariants: [services §3](services.md#3-filter-engine).

## 5. Measured results

*In short: one line per study; the JSON beside it is the evidence.*

All on a development Mac (arm64, Python 3.12), synthetic data, one run each. Model labels are anonymised (open model A, small models B and C, reference model D).

| Study (date) | Result | Evidence |
| --- | --- | --- |
| Filter tiers, canonical events (18 Oct) | 100k selective rules: p95 5.5 ms/event, 256 events/s; 100k overlapping: p95 361 ms, 3.1/s; 1m tiers hit the 1 GiB limit (251k / 387k registered). 1m cached reads at 1.7 μs each. 100/100 generated rules matched independent totals over 14,018 deliveries | [performance.json](../../benchmarks/results/performance.json), [spread.json](../../benchmarks/results/spread.json), [value-reads.json](../../benchmarks/results/value-reads.json), [full-match.json](../../benchmarks/results/full-match.json), [latency.svg](../../benchmarks/results/latency.svg) |
| Shared predicates + clock index (18 Oct) | 100k rules: selective p95 6.2 → 3.7 ms (184 → 376/s), overlapping 594 → 242 ms (2.1 → 7.4/s); 1 family evaluation and 15 time-index probes per event; memory +10 % | [before](../../benchmarks/results/optimization-before.json), [after](../../benchmarks/results/optimization-after.json) |
| First agent run (18 Oct) | Gold 100/100. Agents 78/112 strict (stat prompts 68/100, negatives 10/12) | [agents.json](../../benchmarks/results/agents.json), [cases.json](../../benchmarks/results/cases.json) |
| Goal agent + compiler (18 Oct) | Same 100 prompts 94/100 (median 8.7 s); quality cohort 96/100; clarifications 10/12, then 12/12 after the unresolved-player guard | [baseline](../../benchmarks/results/agents-improved-baseline.json), [quality](../../benchmarks/results/agents-improved-quality.json), [conversations](../../benchmarks/results/agents-conversations-final.json), [serial](../../benchmarks/results/agents-serial-smoke.json) |
| Balanced wording (18 Oct) | 88/90 final (clear 30, average 30, poor 28); controls 10/10; both misses guessed instead of clarifying | [results](../../benchmarks/results/agents-balanced.json), [cases](../../benchmarks/results/agents-balanced-cases.json) |
| Model strength (18 Oct) | Open model A 94–97/100 on balanced, 11/12 transfer; reference D 96/100; small B/C 0–5/12 on the screen. Compact prompt cut request size 16 %; its accuracy gain did not repeat | [model-strength/](../../benchmarks/results/model-strength/) |
| Structured output (18 Oct) | A 17/19 with prompt or schema; B 2–3/19. Schema fixes shape, not meaning; some routes return 429 for schema requests | [schema-study/](../../benchmarks/results/schema-study/) |
| Event-data skill (18 Oct) | A 95 → 97/100 with the skill; fresh wording 17/20 either way; D 19 → 20/20 additive. Kept optional | [data-skill/](../../benchmarks/results/data-skill/) |
| SPADL golden sets (21 Oct) | Questions 23/25 → 25/25 on the local model, replays 34/40 → 41/42; full and compact SPADL dictionaries tie (the runtime keeps the full one plus `lookup_spadl`). SPADL changed some expected values: saves include off-target touches, touches count every action except carries, interceptions include blocked passes | [spadl/](../../benchmarks/results/spadl/) |

The filter tiers predate SPADL (canonical events); `./dev benchmark filters` now replays SPADL actions. The agent cohorts were translated to SPADL and their gold rechecked, but not re-run on a model.

## 6. Doubles

*In short: test and benchmark stand-ins, never imported by `backend/`.*

`benchmarks/doubles/` holds the recording reader (`recording.py`), synthetic event adapter (`events.py`), scripted agents, seeded config and `spadl.py` (SPADL and MA3 rows: a simple map for hand-authored [fixtures](fixtures.md), ETL's converter for shipped recordings). A static test checks no backend module imports recordings, fixtures or doubles.
