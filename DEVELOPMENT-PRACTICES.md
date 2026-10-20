# Development practices

Keep each service modular and easy for people and coding agents to change. Python is the backend default; use small classes where they own state or replaceable dependencies. Prefer composition over inheritance-heavy frameworks.

```text
HTTP / UI view → application service → domain model / pure engine
                         ↓
                repository or adapter → database / external API
```

| Layer | Owns | Must not do |
| --- | --- | --- |
| `models/` | Typed inputs, rules, events and invariants | Open databases or call models/APIs |
| `services/` | Use cases, orchestration, state transitions | Depend on vendor JSON keys or HTTP route objects |
| `repositories/` | SQL, persistence and transactions | Decide UI behaviour or interpret user requests |
| `adapters/` | Translate external events, model APIs and replay sources | Leak provider-specific fields into the rule engine |
| `routes/` / frontend views | Validate/translate requests, render responses | Open DB connections or implement calculations |
| `agents/` | Define semantic goals; compile bounded rules; validate/repair | Execute arbitrary model output or bypass typed contracts |

**One responsibility per file.** Split files when their reasons to change differ, not at an arbitrary line count. Keep related logic together. Avoid catch-all helpers and duplicated business rules. Existing foundation code can migrate incrementally; new features follow these boundaries.

**Use Microsoft Agent Framework for agent orchestration.** Model-based goal/coding roles use the SDK, and workflow stages use its typed executors and routing. Compile bounded semantic goals deterministically when no further interpretation is needed; avoid a redundant model call just to translate fields. Keep filters and validation separate from model calls. Fixture mode substitutes agent doubles inside the same workflow; do not replace the framework with a parallel custom orchestration implementation.

**Inject dependencies.** Construct adapters/repositories in one composition root. Tests replace them without changing services. A provider-specific key change belongs in its event adapter. The fixture replay is an optional source and UI, not the production pipeline.

**Validate at boundaries.** Use strict typed event/rule models. Treat LLM output as untrusted data. Reject unsupported operators, unavailable fields and wrong-match rules. Never use `eval`/`exec` for a structured filter. Future arbitrary Python requires a separate isolated executor.

**Keep ownership clear.** ETL calculates standard stats. The backend requests those values through GraphQL. Only custom rules use the shared event index and custom accumulator; no per-viewer event consumer. Canonical event IDs, revisions and tombstones must survive adapters.

**Persist deliberately.** Repositories own transactions. Save replay position and changed results together. Do not report a successful mutation before commit. Explain recovery, retry and single-process limits; a development stub is not proof of distributed durability.

**Test observable behaviour.** Use synthetic events with expected results, exact time boundaries, corrections, duplicates, unseen fields and broad filters. Compare indexed results to a simple reference evaluation. Test candidate counts rather than fragile performance timings. Use real Postgres for persistence tests, and verify the running API/UI before calling integration complete.

**Optimise from the algorithm.** State the invariant and costs of lookup, candidate evaluation, updates, memory and output separately. Prefer general indexes and shared work over branches for particular examples. Measure realistic workloads before adding complexity; many matching results still require many updates. Keep expensive benchmarks opt-in and distinguish measured capacity from projections.

**Evaluate understanding separately.** Freeze prompts and independent expected answers before model runs. Compare clear, average and poor wording of the same intents. Supply prepared user replies only after clarification, count unjustified guesses as failures, and report first-turn and final accuracy separately. Never give the model gold rules or expected values, or replace older results with an easier corpus.

**Ground agents in the active data contract.** Keep feed meanings in a versioned adapter-owned reference; derive types from executable models. Do not treat public provider definitions as a wire schema. Review semantic changes explicitly, and keep data skills free of benchmark prompts, gold rules and expected totals. Evaluate reference changes on frozen regression and separate transfer cases before enabling them.

**Local model configuration stays local.** Commit only generic variable names and an example configuration. Keep URLs, keys and machine-specific model routing in ignored files. Model failures must be visible; fixture mode must identify itself. Never commit request logs or provider response dumps.

**Document briefly.** Service README: purpose, run command, boundaries and current limits. Put deeper contracts in service `docs/`. Mark planned versus implemented. Preserve source provenance for synthetic/vendor-inspired data. No unsolicited CI, new infrastructure or cloud deployments.
