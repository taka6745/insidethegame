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

| Agent | Runs | Prompt | Returns | Default effort |
| --- | --- | --- | --- | --- |
| `minute-summariser` | Once per closed minute with events | `minute-summary.v3` | JSON `{"summary": ...}` | minimal |
| `context-compressor` | When a compression rule fires | `context-compression.v2` | JSON `{"summary": ...}` | minimal |
| `match-analyst` | Every 5 match minutes, half and full time ([analysis](analysis.md)) | `match-analyst.v4` | JSON observations citing trend numbers, checked by `analysis/validator.py` | (role default) |
| `narrative-author` | Once per bucket per step | `narrative-author.v7` | Plain text, one to three sentences | low |

Default effort is the local stack's; on Azure every role runs `gpt-6.1-sol` at `low`, its lowest effort (`infra/variables.tf` `agents`). Follow narratives use the `narrative-author` role with the `subscription-author` prompt ([follows](follows.md#4-authoring)).

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

**Live switch per role.** The service also reads the user backend's `GET /model-roles` (ETag-cached; edited under `/dev/config/models`). A role with a deployment there runs on that deployment at the same endpoint with its effort; an empty one, or an unreachable backend, keeps the environment's settings. On Azure the alternates `gpt-6-luna` and `gpt-5-mini` are deployed beside `writer` for this.

Check the connection for all four roles: `python -m narrative_engine.agents.llm`.

## 4. Prompts

*In short: versioned runtime copies; the originals stay untouched.*

Runtime templates live in `agents/prompts/` with `{placeholder}` variables (JSON braces are left alone). Their first paragraphs keep the original wording from [design/example-prompts](../design/example-prompts/), which a test checks. A new version gets a new file name (`narrative-author.v2.txt`), and every block and narrative records the version that produced it. v2 of the author prompt stopped premature "final whistle" lines and invented xG; v3 replaces the fixed bucket paragraph with the user backend's audience descriptions (`{user_type}` carries that text). `narrative-author.v4` and `minute-summary.v2` add a six-line SPADL glossary (event lines follow SPADL action types and results; carries are inferred dribbles), placeholders unchanged. `narrative-author.v5` adds `{storylines}` (the focus marked) and `{match_trends}` and asks the author to advance the focus storyline rather than retell the minute. `match-analyst.v1` describes only its inputs, the reply schema and the grounding rule; it names no football patterns, so the model draws its own conclusions. `match-analyst.v2` (same placeholders) describes the side-by-side trend table and the reply schema, with confidence as a level (`low`, `medium`, `high`; `high` needs a row from a window other than `last5`). `match-analyst.v3` replaces v2's fixed limits (observations, evidence rows, confidence levels, the short window's cap) with placeholders the engine fills from the storyline policy's `analysis` section (`validator.prompt_limits`), so the prompt and the validator read one source. `match-analyst.v4` (same placeholders) asks for labels, headlines and outcomes in plain football words, using the indicators' meanings listed after the table, and keeps indicator ids to the evidence rows. `subscription-decision.v2` drops v1's `{follows}` block: the shared state carries no viewer text, and each topic's focus goes only in its own questions ([follows](follows.md)). `narrative-author.v6` (same placeholders) describes the trend units and drops v5's example excerpt, whose conclusions the model copied. `minute-summary.v3` and `context-compression.v2` name the example teams "Team A"/"Team B" and no player, so no real or demo club is copied. Prompts describe inputs and outputs only; grounding is enforced in code (the validators and their repair turn), never by rules or phrase lists in the prompt. The user backend's prompt migrations (`021`, `023`, `025`, `029`, `030`) seed the same text; `023` and `029` make a version with new placeholders active even over an edit, since the engine accepts only templates with the shipped placeholders.

The service takes each role's active template from the backend's prompts API (`prompt_source.HttpPromptSource`), if its placeholders equal the shipped file's; otherwise the work pauses and `/health` is 503 ([core §4](core.md#4-audience-targets)). Only tests and devtools use the shipped files directly.

## 5. Fakes (`tests/doubles/fake_agents.py`)

*In short: deterministic text with no model calls, for tests and offline runs.*

`FakeAgents` returns predictable summaries and narratives, records every call and its variables, and can delay the author to test concurrency. Tests use it directly; devtools select it with `--agents fake`. It lives in `devtools/`, which the service image excludes.
