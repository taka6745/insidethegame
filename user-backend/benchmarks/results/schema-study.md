# Schema constraints and remaining interpretation failures

Measured 2026-10-18. **Schema constraints improve output shape; they do not make a small model understand the request correctly.** The 20B route kept 17/19 correct with both formats. The 3B route remained unsuitable for autonomous stat creation.

## What was wrong

The previous reference-model run had four misses: two missed clarifications, an inferred team restriction, and a minutes/seconds error. Compacting the prompt had removed the explicit rule that bare match-time numbers mean minutes. That rule is restored in both modes; field descriptions also explain time units and unrestricted scopes.

The two remaining 20B misses in the final schema confirmation are valid JSON with wrong meaning:

| Request | Actual interpretation | Required behaviour |
| --- | --- | --- |
| “track passing for both sides” | Assumed pass count | Ask count or distance; use the prepared reply only after asking |
| “Mbappé saved shots in the second half.” | Goalkeeper `save` events by Mbappé | Shooter `shot` events with `outcome=saved` |

The 3B model invented period restrictions, narrowed all headed contacts to one event category, omitted requested constraints and accepted unsupported requests. It also produced goals that failed cross-field validation. These are not all JSON-format problems. The previous 8B run likewise dropped player/team constraints and had schema failures; raw invalid outputs from that older run were not retained, so exact malformed fields cannot be reconstructed.

## Paired comparison

Nineteen diagnostic cases: the original 12-case model screen plus seven cases covering known failures. Same frozen gold events and prepared clarification replies, no expected results in model context. This is a failure-focused development cohort, not a held-out accuracy estimate. Models ran sequentially; two cases ran concurrently, with prompt/schema order alternating within each case. Deadline: 30 seconds per turn, 600 seconds per suite.

| Model | Format | Correct | Median conversation | Model calls |
| --- | --- | ---: | ---: | ---: |
| Small model B (3B) | Prompt + compact schema | 2/19 | 1.52 s | 51 |
| Small model B (3B) | Structured schema | 3/19 | 0.98 s | 22 |
| Open model A (20B) | Prompt + compact schema | 17/19 | 5.94 s | 23 |
| Open model A (20B) | Structured schema | 17/19 | 3.38 s | 21 |

The 20B prompt path recorded two invalid-JSON attempts; its schema path recorded no goal-output failures. Lower latency is an observation under this gateway's routing/load, not an intrinsic model speed guarantee. Protocol mode can select a different route. [All paired results](schema-study/comparison.json).

After closing a local numeric-string coercion loophole, a separate schema-only confirmation gave **3B: 2/19, median 1.05 s; 20B: 17/19, median 4.16 s**. All returned model names matched their configured allowlists. The 20B minute-bound case passed; the two semantic misses above persisted. This repeat is not paired with a new prompt-mode run. [Final strict-type confirmation](schema-study/strict-confirmation.json).

Reference-model regression rerun: **2/4 passed** with the corrected prompt, one still guessed the passing metric, and the time-bound case was blocked by HTTP 429. That last case is unverified on the reference model. [Four original reference misses](schema-study/reference-regressions.json).

## What changed

```text
Typed models → generated schema → SDK response_format + prompt context
                                            ↓
                                strict JSON validation
                                            ↓
                                deterministic compiler
```

- Optional `AGENT_GOAL_OUTPUT_MODE=schema`; default remains `prompt`.
- One generated contract for protocol and context. Every property required, additional properties rejected, `[]`/`null` meanings explicit. Local strict JSON validation rejects missing fields, unknown fields, wrong types and invalid cross-field combinations even if the provider ignores constraints.
- Goal/Clarification models remain the source of truth. New scalar fields propagate; future nested models and arbitrary maps fail construction until their wire support is implemented. Contract/prompt hashes identify the evaluated versions. New capabilities still require compiler and adapter changes.
- Safe diagnostics retain attempt, bounded field path and error type. Unknown extra keys are masked; rejected values and provider bodies are not saved. These diagnostics feed the bounded retry.
- Existing gold evaluation still checks every delivery prefix and canonical constraints. A valid rule matching a misunderstood goal is still a failure.

Microsoft Agent Framework exposes the [`response_format` structured-output option](https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs). This implementation uses the installed SDK's strict JSON Schema transport, then validates independently. Provider acceptance alone does not prove constrained decoding.

## Provider compatibility findings

A tiny enum-only [canary](schema-study/canary.json) worked for 3B, 20B and the reference route; 8B returned 429. The full contract exposed more problems:

- Protocol-only full-schema smoke: the 20B route emitted invented fields and omitted required fields. Adding the same schema to model context changed its three-case smoke from 0/3 to 3/3. These small runs motivated the implementation, not a general accuracy claim. [Protocol-only](schema-study/protocol-only-smoke.json) · [Schema plus context](schema-study/schema-context-smoke.json).
- In a later paired availability probe, 8B and the reference route answered ordinary requests but returned 429 for schema requests. These are **schema-route availability failures**, not measured reasoning failures or proof those models inherently cannot support schemas. [Availability probe](schema-study/availability.json).
- Structured-output support is route/model dependent; some routes document JSON-mode limitations. No fallback silently removes constraints in this application.

Keep the stronger working route for stat interpretation; the current evidence does not justify replacing it with 3B. Before enabling schema mode by default, rerun the full 100-case cohort and provider compatibility checks on the deployment route. A future semantic verifier or smaller intent-selection contract is a separate experiment, not a proven fix here.

[Prompt snapshot](../prompts/goal-prompt-v3.txt) · [Prompt schema](../prompts/goal-prompt-v3.schema.json) · [Structured prompt](../prompts/goal-structured-v1.txt) · [Structured schema](../prompts/goal-structured-v1.schema.json) · [Run the comparison](../README.md#compare-pinned-models-and-prompt-variants)
