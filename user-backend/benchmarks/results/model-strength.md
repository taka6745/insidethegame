# Model strength and prompt size

Measured **18 October 2026**, using the local development model gateway and the real Microsoft Agent Framework workflow. **20B is a practical development candidate; the tested 3B/8B models are not reliable enough for this task.** Model calls happen when defining a custom stat, not for each live event. This is a bounded task evaluation, not an enterprise readiness claim.

## Small screening run

Twelve identical cases per model/variant: three intents in three wording bands plus three unsupported controls. “New” is the first compact prompt, before the final wording adjustment.

| Model | Old → new meaning passes | Old → new median conversation |
| --- | ---: | ---: |
| Llama 3.2 3B | 0/12 → 2/12 | 1.98s → 1.52s |
| Llama 3.1 8B | 3/12 → 5/12 | 8.75s → 2.62s |
| GPT OSS 20B* | 11/12 → 11/12 | 3.17s → 2.15s |
| Dots 3 reference | 11/12 → 11/12 | 8.21s → 6.85s |

*The screen initially omitted a returned 20B alias from its allowlist: only 4/12 passes per variant qualified as identity-verified. Those records remain unchanged. The subsequent 100-case run explicitly allowed the verified catalogue aliases and checked every successful call. The reference was higher-ranked in the local catalogue; its size is not independently established.*

The 3B model improved its JSON/schema compliance but repeatedly asked unnecessary questions. The 8B model still omitted or added constraints. Valid JSON alone does not make a correct stat.

## Paired 100-case experiment

Thirty known intents × clear/average/poor wording, plus ten unsupported controls. Prepared replies are sent only if the agent actually asks. A pass may include up to two follow-ups; timings exclude human thinking time. Poor prompts deliberately include requests requiring clarification.

| GPT OSS 20B | Original | Compact v1 |
| --- | ---: | ---: |
| Strict passes | 94/100 | 97/100 |
| Clear / average / poor | 30 / 27 / 29 of 30 | 30 / 30 / 28 of 30 |
| Unsupported controls | 8/10 | 9/10 |
| Median conversation | 4.08s | 2.93s |
| p95 conversation | 12.96s | 7.04s |
| HTTP model calls | 123 | 113 |
| Median serialized request | 8,667 bytes | 7,288 bytes |

The prompt and inline schema reduced median request size **16%**. Reported aggregate tokens fell from 320,549 to 240,876, but providers did not supply an estimation flag; these are reported counts, not verified billing measurements. Calls include follow-ups and retries. Latency includes model/network time; it is separate from filter-algorithm performance.

The v1 misses were headed-touch interpretation, guessing a vague passing request, and accepting one unsupported request. The final wording explicitly distinguishes everyday “headed touches” from the feed's `touch` event category. The confirmation results below are separate; they do not replace the paired result.

## Final prompt confirmation

| Model / set | Strict passes | Median conversation | p95 conversation |
| --- | ---: | ---: | ---: |
| GPT OSS 20B / balanced 100 | 94/100 | 2.81s | 8.08s |
| GPT OSS 20B / transfer 12 | 11/12 | 0.90s | 10.84s |
| Dots 3 reference / balanced 100 | 96/100 | 7.85s | 14.52s |

All successful responses in these runs matched the allowed model identities. The reference scored clear **30/30**, average **28/30**, poor **28/30**, controls **10/10**; it missed two required clarifications, altered one set of constraints and produced one wrong calculation. Its 107 calls had no workflow timeouts. The two-point difference from the final 20B run is too small and unrepeated to establish a dependable accuracy ranking. The balanced confirmation scored clear **29/30**, average **29/30**, poor **27/30**, controls **9/10**. Its six failures included two schema/output failures, two wrong calculations, one missed clarification and one accepted unsupported request. The transfer miss incorrectly declined supported second-half completed-pass distance.

**The faster responses repeated; the accuracy gain did not.** The explicit headed-touch wording still failed on the typo-heavy request; it is a clearer feed contract, not a demonstrated fix for that miss. Retain the bounded compiler/validation, use clarification for incomplete requests, and keep the existing model-selection configuration until broader evaluation supports a cheaper default. A stronger model is not a guaranteed repair for every valid-but-misunderstood goal.

[Final 20B evidence](model-strength/confirmation-20b.json) · [Transfer evidence](model-strength/transfer-20b.json) · [Reference evidence](model-strength/confirmation-reference.json)

## Method and limits

- Frozen [original](../prompts/goal-baseline.txt), [compact v1](../prompts/goal-compact-v1.txt) and [compact v2](../prompts/goal-compact-v2.txt) prompts. Original/full schema versus compact/inline schema changes two factors together.
- Same validator, deterministic compiler, repair budget and oracle. Models receive match context, semantics and conversation, **never gold rules or expected values**. Check all 35 event-delivery prefixes, late backfill and exact constraints.
- Variants alternate order within each case; two cases run concurrently. Models run sequentially. Screen: 35s per turn; full comparisons: 45s per turn; 1,000s suite deadline (transfer: 300s). Up to two scripted replies. All failures remain in the denominator.
- Requested IDs are pinned to model groups; returned identities are checked on every successful call. Same-model provider routing can change. Identity is provider-reported, not independent verification of model weights. `no-cache` is requested.
- Provider route/load varied: the same 20B identity sometimes took over 25s in exploratory calls. Speed differences are not purely caused by model size or prompt size.
- These are single runs over synthetic, known football semantics. Transfer cases use fresh wording and additional known gold intents, not an untouched domain. Repeated accuracy can vary. Earlier automatic-routing scores are not controlled comparisons to these models.
- The original recorded runs used an empty diagnostic list on workflow timeout; it must not be interpreted as proof of zero schema failures. Runtime now marks unavailable timeout diagnostics `null`. HTTP observations still preserve calls/cancellations.

[Screen evidence](model-strength/screen.json) · [Paired 20B evidence](model-strength/paired-20b.json) · [Run it yourself](../README.md#compare-pinned-models-and-prompt-variants)
