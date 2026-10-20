# Event-data reference skill

The goal agent can read a small, versioned data dictionary before defining a stat. It explains **whose action a record represents**, qualifiers, units, corrections and missing data. It contains no match records, expected totals or benchmark requests.

```text
Vendor feed → event adapter → canonical Event model
                    │                  │
             reviewed meanings    generated types
                    └────────┬─────────┘
                         data skill
                             ↓
                     goal → rule → checks
```

Enable experimentally with `AGENT_DATA_SKILL=feed ./dev up backend`; `off` is the default. It works with either `AGENT_GOAL_OUTPUT_MODE=prompt` or `schema`, and adds no extra model call. In skill mode, data mappings come from the active adapter reference instead of the fixed metric-mapping section. General decision, clarification, time-language and output instructions remain unchanged. This tests a data-reference replacement, not an isolated change to a single sentence.

| File | Responsibility |
| --- | --- |
| [SKILL.md](../backend/agents/skills/event-data/SKILL.md) | How to read the supplied data dictionary |
| [Feed profile](../backend/adapters/feed_profiles/opta-inspired-v2.json) | Application-owned meanings and coverage |
| [Reference builder](../backend/adapters/feed_reference.py) | Derive types, enums and bounds from the current event model; check dictionary coverage |
| [Adapter](../backend/adapters/events.py) | Select the profile belonging to this feed and normalize vendor keys |
| [Composition root](../backend/lab_factory.py) | Pass that adapter's reference into the workflow |

The current fixture is **synthetic and Opta-inspired**, not a licensed Opta feed. [Opta's public event definitions](https://www.statsperform.com/opta-event-definitions/) describe consistent collection definitions, including distinctions between shots, saves and body-part qualifiers. They are useful semantic background, not a complete wire-format specification or a promise that schemas never change. The runtime dictionary documents our adapter's actual contract; do not copy vendor IDs from public examples into the filter engine.

## When the data changes

- **Vendor key changes:** update the adapter and its contract tests. Keep the internal meaning stable where possible; the agent does not need vendor keys.
- **Types/enums/bounds:** the reference reads these from the typed event model and fingerprints that schema. No second handwritten type schema.
- **New fields/categories:** missing dictionary coverage fails construction until reviewed. Removed entries fail too. New rule operators still require compiler/executor support.
- **Meaning changes:** review the profile, bump its contract ID and replay contract fixtures. A schema hash cannot detect a semantic change such as “corner awarded” becoming “corner taken.” No automatic discovery is claimed.

Profiles are trusted application resources. Uploaded recordings cannot supply a profile or skill instructions. The lab's replacement recordings retain the same adapter. Other providers need an adapter with its own `data_reference()` implementation; unsupported profiles must not silently inherit this synthetic feed's definitions.

## Check usefulness

The standalone comparison supports `--variants current skill` and `--variants schema schema_skill`. Each pair uses the same output schema, compiler, gold oracle and transport mode. Skill hashes, prompt/schema hashes, reported model identities, retries, latency and token counts are retained.

For an additive ablation, `--variants current skill_added` preserves the original instructions and adds exactly the same reference; `schema schema_skill_added` does so with structured output. These are benchmark-only variants for separating added knowledge from replacing the fixed mappings. They are not the runtime mode: retaining two independently maintained data mappings would create a drift risk.

`--cohort data-transfer` adds 20 frozen requests written without reading the skill: new wording and fictional entity IDs, 16 known stat intents plus four unavailable-data controls. Four stats require clarification. Gold ledgers remain independent of the model, every delivery prefix and late backfill is checked, and redundant constraints fail even if fixture totals happen to match. This is wording/catalogue transfer on a reused synthetic match, not a new-domain or production-feed test.

The original balanced 100-case cohort remains unchanged. Neither its answers nor the transfer answers enter model context. Mutation checks ensure the oracle still rejects wrong actor categories and extra scope. The skill and cases stay frozen during live evaluation; results are evidence, not an invitation to rewrite the gold to fit an answer.

These comparisons supply an empty standard-stat catalogue and test custom-stat interpretation. They do not establish skill-mode quality for reusing real ETL catalogue stats. Raw event coverage and upstream computed-stat availability are separate contracts; evaluate that combination before promotion.

[Evaluation harness](../benchmarks/README.md#compare-pinned-models-and-prompt-variants)

[Measured results](../benchmarks/results/data-skill.md): small gains in some runs, regressions in others; optional until broader evidence supports promotion.
