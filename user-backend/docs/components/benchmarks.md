# Benchmarks and fixtures

> **In short:** opt-in evidence outside the runtime: the question and replay golden sets, the 100-case custom-stat corpus, model and prompt comparisons, and filter-engine performance tiers. Test doubles and synthetic fixtures live here and in `fixtures/`; the runtime image contains neither.

| | |
| --- | --- |
| **Code** | [`benchmarks/`](../../benchmarks/), [`fixtures/`](../../fixtures/) |
| **Full guide** | [benchmarks/README.md](../../benchmarks/README.md), [measured results](../../benchmarks/results/README.md) |
| **In pytest** | `test_question_golden.py`, `test_replay_golden.py` (scripted decisions); everything else is opt-in |

## 1. Golden sets

*In short: the real agents with scripted or live model decisions.*

| Set | Command |
| --- | --- |
| Questions (`question_cases.json`) | `python -m benchmarks.question_inprocess --agent fixture` (scripted) or `--env-file ../.local/backend-llm.env` (local model) |
| Replays (`replay_cases.json`) | `python -m benchmarks.replay_eval --agent fixture` or `--agent local`; `./dev benchmark replay` |

In process, snapshots are cut from the shipped Riverton Rovers–United recording; SPADL actions come from its MA3 stream through ETL's converter (`etl/reference/spadl.py`) and standard stats from ETL's reference catalogue (`etl/reference/catalogue.py`), so no stack is needed. Both sets were re-baselined to SPADL on 21 October 2026 ([before/after](../../benchmarks/results/spadl-golden.md)). Scripted mode replays each case's recorded decision through the real agents, planner, compiler, rule engine and ETL-row answers. Replay key-moment cases run against the archived earlier recording (`narrative-engine/fixtures/archive/`) with the narrative fixtures bound to it; the rest see no narratives.

## 2. Other benchmarks

*In short: understanding and algorithm cost, measured separately.*

`./dev benchmark filters` (no model or network; rules over the 2,710 SPADL actions of Riverton Rovers–United), `./dev benchmark values`, `./dev benchmark agents` (calls the configured model). The agent corpora keep their hand-written intents and event weights; `spadl_corpus.py` translates their rules with migration 020's vocabulary map, and an action carries its source event's weight. Intents SPADL cannot express (cards) expect a refusal or catalogue reuse; pass counts gained the corners SPADL counts as passes. Model and prompt comparisons (`benchmarks.model_strength`) record requested and returned model labels, hashes, tokens and latency. Neither benchmark is a production capacity guarantee.

## 3. Doubles and fixtures

*In short: never imported by `backend/`.*

`benchmarks/doubles/` holds the recording reader, scripted agents, seeded config and `spadl.py` (SPADL and MA3 rows for doubles: a simple map for hand-authored fixtures, ETL's real converter for shipped recordings) used by tests and golden sets. `fixtures/filter-lab.json` is 35 hand-authored synthetic deliveries with corrections and deletions ([notes](../../fixtures/filter-lab.md)). A static test checks no backend module imports recordings, fixtures or doubles.
