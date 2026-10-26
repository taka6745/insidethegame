# Agents

> **In short:** four Microsoft Agent Framework agents on Azure AI Foundry (Azure OpenAI deployments): the minute summariser, the context compressor, the match analyst and the narrative author. Each has its own model, reasoning effort and endpoint, so any one can move to a stronger model without touching the others. Deterministic fakes stand in for tests and offline runs.

| | |
| --- | --- |
| **Status** | Implemented · tested (mocked API); on Azure every agent uses Foundry deployment `writer` = `gpt-6.1-sol` (effort low) |
| **Code** | [`narrative_engine/agents/`](../../narrative_engine/agents/): `llm.py`, `prompts/`; fakes in [`tests/doubles/fake_agents.py`](../../tests/doubles/fake_agents.py) |
| **Libraries** | `agent-framework-core`, `agent-framework-openai`, `openai` |
| **Interface** | `summarise(variables, prompt)`, `compress(variables, prompt)`, `analyse(variables, prompt, feedback)`, `author(variables, prompt, feedback)` → `AgentResult` |
| **Tests** | `test_llm_agents.py` |

## 1. The four agents

*In short: three shared, neutral agents and one per-bucket author.*

| Agent | Runs | Prompt | Returns |
| --- | --- | --- | --- |
| `minute-summariser` | Once per closed minute with events | `minute-summary.v3` | JSON `{"summary": ...}` |
| `context-compressor` | When a compression rule fires | `context-compression.v2` | JSON `{"summary": ...}` |
| `match-analyst` | Every 5 match minutes, half and full time ([analysis](analysis.md)) | `match-analyst.v4` | JSON observations citing trend numbers, checked by `analysis/validator.py` |
| `narrative-author` | Once per bucket per step | `narrative-author.v8` | Plain text, one or two sentences |

Reasoning effort is sent only when `OPENAI_EFFORT` (or `OPENAI_EFFORT_{ROLE}`) is set; on Azure every role runs `gpt-6.1-sol` at `low`, its lowest effort (`infra/variables.tf` `agents`). Follow narratives use the `narrative-author` role with the `subscription-author` prompt ([follows](follows.md#4-authoring)).

Calls are stateless: each run gets a freshly built prompt and no conversation history (design principle 4). A summary reply that is not valid JSON gets one follow-up asking for the JSON only; an empty author reply is retried once; an analyst reply with no JSON object gets one follow-up, then goes to the validator as it is. The grounding checks ([analysis](analysis.md)) allow one repair turn per analysis and per excerpt: `analyse` and `author` take `feedback` (the earlier reply and the reasons) and continue that conversation.

## 2. How a call is made

*In short: Agent Framework agent → OpenAI chat completions client → Foundry's `/openai/v1` endpoint.*

1. `LLMAgents` builds one Agent Framework `Agent` per role, with a `default_options` `reasoning_effort` when set.
2. `chat_client()` creates the `OpenAIChatCompletionClient` on an `AsyncOpenAI` client. This is the only provider-specific code; change it to use another kind of model API.
3. The OpenAI client retries rate limits, server errors and dropped connections (4 retries). Auth failures fail at once.
4. Errors become `LLMError` with only the status code, never the response body, which can echo part of a key.
5. The result records the model that answered (on Azure AI Foundry; any other endpoint is recorded as `local-model`, so no local model id reaches the store or APIs), the prompt version and token counts.

## 3. Model settings

*In short: `OPENAI_<SETTING>_<ROLE>` overrides `OPENAI_<SETTING>` for one role.*

| Setting | Variable | Per-role override |
| --- | --- | --- |
| Endpoint (includes `/v1`) | `OPENAI_BASE_URL` | `OPENAI_BASE_URL_AUTHOR`, `_SUMMARY`, `_COMPRESSION`, `_ANALYST` |
| Key | `OPENAI_API_KEY` | `OPENAI_API_KEY_<ROLE>` |
| Model or deployment | `OPENAI_MODEL` | `OPENAI_MODEL_<ROLE>` |
| Reasoning effort | `OPENAI_EFFORT` (unset = not sent) | `OPENAI_EFFORT_<ROLE>` |

Unset `OPENAI_*` settings fall back to the local model's `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL` and `LOCAL_LLM_API_KEY` (a dummy key when unset); the local stack passes them from the ignored `.local/backend-llm.env`, as for the user backend.

Example, a different author only: `OPENAI_MODEL_AUTHOR=gpt-6-luna OPENAI_EFFORT_AUTHOR=medium`. In Azure the same is done in Terraform ([deployment §3](../deployment.md#3-changing-a-model)).

**Live switch per role.** The service also reads the user backend's `GET /model-roles` (ETag-cached; edited under `/dev/config/models`). A role with a deployment there runs on that deployment at the same endpoint with its effort; an empty one, or an unreachable backend, keeps the environment's settings. Terraform defines the alternates `gpt-6-luna` and `gpt-5-mini` beside `writer` for this.

Check the connection for all four roles: `python -m narrative_engine.agents.llm`.

## 4. Prompts

*In short: versioned runtime copies; the originals stay untouched.*

Runtime templates live in `agents/prompts/` with `{placeholder}` variables (JSON braces are left alone). Their first paragraphs keep the original wording from [design/example-prompts](../design/example-prompts/), which a test checks. A new version gets a new file name, and every block and narrative records the version that produced it. Prompts describe inputs and outputs only; grounding is enforced in code (the validators and their repair turn), never by rules or phrase lists in the prompt.

Current versions: `narrative-author.v8`, `match-analyst.v4`, `minute-summary.v3`, `context-compression.v2`, `subscription-decision.v2`, `subscription-author.v1`. Earlier versions stay in `agents/prompts/` and in the backend's `narrative_prompts` table, seeded by its prompt migrations ([migrations](../../../user-backend/docs/components/migrations.md)); a version with new placeholders is made active even over an edit, since the engine accepts only templates with the shipped placeholders.

The service takes each role's active template from the backend's prompts API (`prompt_source.HttpPromptSource`), if its placeholders equal the shipped file's; otherwise the work pauses and `/health` is 503 ([core §4](core.md#4-audience-targets)). Only tests and devtools use the shipped files directly.

## 5. Prompt caching

*In short: the shared match material comes first, the per-bucket part last, and the first bucket warms the cache.*

The model API caches prompt prefixes automatically once they pass its minimum length (1024 tokens on Azure OpenAI), so a prompt is cache-friendly only while everything that differs between calls sits at its tail. `narrative-author.v8` orders its segments that way: the static instructions, then the match material shared by every bucket of a step (`{trigger_reason}`, `{game_state_statistics}`, `{storylines}`, `{match_trends}`, `{key_event_ledger}`, `{combined_match_context}`, `{match_events}`), then the per-bucket `{user_type}` and `{narrative_excerpts}`. A `/dev/` edit that moves a per-bucket placeholder forward keeps working but loses the hits. The orchestrator awaits the first bucket's call before gathering the others (`_grounded`), so the siblings find the prefix cached: one call's latency per step. Not cacheable: the summariser and compressor (short, all-new prompts), the analyst's single call per analysis, and anything below the minimum length. `cache_read_input_token_count` from the framework's `usage_details` is recorded as `cached_tokens` beside `prompt_tokens` in every block's and narrative's `tokens` (summed over a step's rewrites), shown by `devtools/report.py` as `N cached`.

## 6. Fakes (`tests/doubles/fake_agents.py`)

*In short: deterministic text with no model calls, for tests and offline runs.*

`FakeAgents` returns predictable summaries and narratives, records every call and its variables, and can delay the author to test concurrency. Tests use it directly; devtools select it with `--agents fake`. It lives in `tests/doubles/`; the image contains only `narrative_engine/`.
