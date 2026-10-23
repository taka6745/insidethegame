# Decisions

> **In short:** bounded classifiers for story follows and claim checks. A decision model answers typed questions about a state (yes/no, choice or score) with probabilities and no free text. Microsoft-Decision-1 on Azure AI Foundry is the model; a chat model constrained to a JSON schema of enums is the local fallback behind the same protocol.

| | |
| --- | --- |
| **Status** | Implemented · tested; used by story follows, their moment clips ([follows](follows.md)) and the claim checks. Azure deployment `decision-1` (DataZoneStandard, 50 requests/minute) |
| **Code** | [`narrative_engine/decisions/`](../../narrative_engine/decisions/): `__init__.py` (questions, answers, `DecisionModel`, `DecisionSettings`), `systemone.py`, `llm.py`; test double [`tests/doubles/fake_decisions.py`](../../tests/doubles/fake_decisions.py) |
| **Tests** | `test_decisions.py` (httpx.MockTransport); `python -m narrative_engine.decisions.systemone` makes one live call and never prints the key |
| **Contract** | [Subscription targets](../../contracts/README.md#subscription-targets) |

## 1. Protocol

*In short: `decide(state, questions) → Decisions`.*

| Question | Answer |
| --- | --- |
| `Noul(instructions, true?, false?)` | `probability` of yes |
| `Choice(instructions, options)` | `choice`, `confidence`, `probabilities` per option |
| `Score(instructions, levels)` (lowest first) | `score` (a level index; Decision-1 may answer between levels), `confidence`, `probabilities` per level |

A declined question is missing from `answers`; an answer outside the question raises `DecisionError`. `model` is the Azure deployment that answered (`local-model` off Azure); `tokens` as for the agents. Decision-1 (`own_capacity`) has its own deployment, paced by `DECISION_REQUESTS_PER_MINUTE`, so its calls never take a slot of the agents' model gate; the `llm` fallback shares the agents' model and takes the gate's `decision` priority (after analyses, before authors). A failure (`DecisionError`, after the retries) pauses the match's work like an unavailable backend: the step is retried with backoff, never written unchecked.

## 2. Settings

*In short: `DECISION_*`, from the environment (locally the ignored `.local/decision.env`).*

| Setting | Meaning |
| --- | --- |
| `DECISION_PROVIDER` | `systemone` (Decision-1) or `llm` (the fallback); default `systemone` when `DECISION_BASE_URL` is set, else `llm` |
| `DECISION_BASE_URL`, `DECISION_API_KEY`, `DECISION_MODEL` | Foundry resource endpoint, key, deployment (`decision-1` in dev). The `llm` provider falls back to `OPENAI_*_DECISION`, `OPENAI_*`, `LOCAL_LLM_*` |
| `DECISION_PATH` | Default `/providers/microsoft/v1/systemone` |
| `DECISION_AUTH` | `api-key` (header), `bearer` (Entra ID token) or `none` |
| `DECISION_MODEL_FIELD` | Body key for the deployment (default `model`; empty leaves it out) |
| `DECISION_MAX_QUESTIONS` | Questions per request (default 1; larger batches are split and sent in parallel). Verified live: 160 questions in one call; local stack and Azure set 128 |
| `DECISION_REQUESTS_PER_MINUTE` | Client-side pacing of every request in the process (0: none). The deployment's limit is requests per minute, one per capacity unit (dev: 10; Azure Terraform: 50) |
| `DECISION_TIMEOUT`, `DECISION_RETRIES` | Seconds (20); retries of 408/429/5xx with backoff and `retry-after` up to 60 s (2; the stacks set 4) |

The SystemOne body is `{"model", "state", "questions": {key: {"type": "noul"|"choice"|"score", "instructions", "criteria"}}}`; the reply `{"model", "answers": {key: …}, "usage": {"input_tokens", "output_tokens"}}`. The fallback sends a strict `json_schema` response format (each answer an enum plus a confidence) and allows one repair turn.

## 3. Users

*In short: three callers, all batched. The viewer's "Follow this story?" offer (D5b) is the user backend's own Decision-1 call, not the engine's.*

| Caller | Questions |
| --- | --- |
| Story follows ([follows](follows.md)) | Per update: a `Score` per candidate topic, plus a novelty `Noul` for each with a last narrative; on a key event of `clips.key_types`, also a clip `Score` per candidate that is not clip-on (D3/D6); one call. The clip counts at its nearest level (Decision-1 returns the expected level) |
| The authors' grounding check (`analysis/validator.claim_reasons_many`) | Per sentence of each excerpt: does it claim a cause / an intent / the result / a comparison, and does the evidence (storyline beats, ledger, trends, statistics, recaps, latest events, trigger) support it? One call per step's drafts. Questions and thresholds: the storyline policy's `claims` section |
| The analyst's grounding check (`analysis/validator.analyst_claim_rejections`) | The same questions for the claims marked `analyst` (seed: `intent`, `result`, `comparison`), per accepted observation and resolve, against the analyst's inputs; one call per check |
