# Data-reference skill experiment

Measured 2026-10-18. **There is a small positive signal, not a reliable general improvement yet.** On the existing 100-case cohort, the 20B route improved from 95 to 97 correct. On fresh wording/catalogue cases it stayed at 17/20. Simply adding the reference helped the stronger reference model by one case, while smaller models remained unreliable. Runtime enablement stays opt-in.

## What the model learned about the data

The [versioned skill](../../backend/agents/skills/event-data/SKILL.md) explains how to read the active adapter's dictionary: event actor, qualifiers, units, corrections and absent fields. For instance, a shot record belongs to the shooter and a save record to the goalkeeper. It contains **no match records, gold filters, expected totals or benchmark requests**.

Types, enum values and bounds come from the executable canonical event model. Human-reviewed meanings live in an adapter-owned JSON profile; new fields or event categories without definitions fail construction. The current profile is synthetic and Opta-inspired, not a licensed Opta wire specification. See [implementation and schema changes](../../docs/components/agents.md#4-event-data-skill-optional).

Two experiments distinguish different changes:

1. **Replacement (`skill`):** replace fixed metric-mapping instructions with the dictionary and skill. General decision/output/time instructions stay unchanged.
2. **Addition (`skill_added`):** retain the original instructions byte-for-byte and add the exact same skill/reference. This secondary experiment isolates added knowledge, but retains duplicated data mappings and is benchmark-only.

Both preserve the output schema, compiler, oracle and repair budget. Structured-output variants use the same comparison with schema mode enabled. The skill makes no additional model call. No facts, prompts or gold answers were changed during evaluation.

## Full 100-case regression: 20B

| Mode | Correct | Median conversation | Calls |
| --- | ---: | ---: | ---: |
| Current fixed mappings | 95/100 | 3.92 s | 113 |
| Data-reference replacement | 97/100 | 4.16 s | 110 |

| Wording | Current | Reference |
| --- | ---: | ---: |
| Clear | 29/30 | 30/30 |
| Average | 28/30 | 29/30 |
| Poor, with prepared clarification replies | 28/30 | 28/30 |
| Unsupported controls | 10/10 | 10/10 |

Three previous misses became passes; one previously passing case became a wrong value. Both variants still guessed the vague passing measure and confused saved shots with goalkeeper saves. This is one run on a previously inspected regression corpus, not held-out evidence or proof that a two-point change is reproducible. [All 200 results](data-skill/balanced.json).

## Fresh wording and fictional IDs: replacement

Twenty requests were independently written without reading the skill, then frozen before inference: 16 stat intents, including four requiring clarification, plus four unsupported-data controls. Player/team names and IDs are consistently remapped. These reuse known gold intents and the same synthetic event history; they are **not an unseen-domain or new-match benchmark**.

| Model | Current | Reference replacement | Median seconds, current → reference |
| --- | ---: | ---: | ---: |
| Small model B (3B) | 0/20 | 0/20 | 0.98 → 1.09 |
| Small model C (8B) | 7/20 | 6/20 | 2.89 → 3.56 |
| Open model A (20B) | 17/20 | 17/20 | 4.36 → 4.32 |
| Reference model D | 19/20 | 18/20 | 9.34 → 8.52 |

The reference-model regression was a saved-shot request: replacement selected `save`, while the baseline correctly selected `shot` with `outcome=saved`. More explanation did not prevent that misunderstanding. [All 160 results](data-skill/transfer.json).

With strict output schema on 3B, reference replacement changed **0/20 to 3/20**. Format constraints therefore uncover a little benefit, but the result is still inadequate for autonomous interpretation. [All 40 structured-output results](data-skill/small-schema.json).

## Secondary additive check

The skill and cases stayed frozen after the first results. Only the integration changed: original instructions plus the same reference, rather than removing the fixed mappings. Each comparison used a fresh paired baseline.

| Model / transport | Current | Reference added | Median seconds, current → added |
| --- | ---: | ---: | ---: |
| Reference model D / prompt | 19/20 | 20/20 | 8.99 → 7.33 |
| Small model B (3B) / schema | 0/20 | 1/20 | See raw report |

The stronger model's one gain was the successful-tackle request previously refused. There were no regressions in that small additive run. This is promising, but **20/20 is not a reliability guarantee** and the additive variant has not been evaluated on the full 100 cases. [Reference-model additive results](data-skill/additive.json) · [3B additive results](data-skill/small-additive.json).

## Why the tests remain useful

- Expected contributions come from existing hand-authored per-event-revision ledgers, not the agent or skill. Every delivery prefix and late backfill is checked.
- Canonical constraints are checked too: an extra team restriction fails even if the fixture totals match. Mutation tests verify rejection of both that mistake and substituting goalkeeper saves for shooter events.
- Clarification replies are sent only when asked. Ambiguous requests must clarify; guessing a gold result is not a pass.
- Runtime context includes catalogue IDs and the data dictionary, never fixture events, future events, gold rules or weights. Tests guard this boundary.
- Original prompts remain byte-for-byte unchanged in the baseline and additive variants. All skill-bearing rows use fingerprint `157b79284e5aac810ef6d63d0d44075431880e7c221e06a67e8481e1fa053f85`; the new cohort was frozen at file hash `d0be212fe5240fe28b15b6d7c5a6c191baea6fa4a0d61efc1ef2d947ea933732`.

Cases alternate variant order; models run sequentially within each suite with concurrency two. Deadlines were 30 seconds per turn, 900 seconds for the main suites, 300 seconds for small structured suites and 420 seconds for the reference additive suite. Some separate suites overlapped on different requested model groups, so latency is especially not a controlled capacity measurement. All rows passed reported-model identity checks; these are provider-reported names, not independent verification of weights. Cache-Control requests no-cache, which a server may ignore.

Request payloads grew: the 20B full-cohort median was about 8.5 KB without the reference and 14.7 KB with it. More context is not free, and no speed advantage is established. All 480 conversations, including failures, remain in the linked reports; model calls include retries and clarification turns. No live calls enter ordinary pytest. Standard-stat catalogue reuse and real licensed feed compatibility were not tested here.

**Decision:** keep the data contract/versioning layer, keep the feature optional, and do not switch to a tiny model on this evidence. The additive result merits a larger independent comparison before promotion; the replacement result does not justify assuming every provider benefits. The active adapter remains the place for vendor key changes, and semantic changes require profile review even if the provider's JSON shape stays the same.

[Frozen reference snapshot](data-skill/reference-snapshot.json) · [Replacement instructions](data-skill/goal-instructions.txt) · [Structured replacement instructions](data-skill/structured-instructions.txt) · [Run guide](../README.md#compare-pinned-models-and-prompt-variants)
