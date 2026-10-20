# Agents

> **In short:** three Microsoft Agent Framework agents on Foundry: the minute summariser, the context compressor and the narrative author. Each has its own model, reasoning effort and endpoint, so any one can move to a stronger model without touching the others. Deterministic fakes stand in for tests and offline runs.

| | |
| --- | --- |
| **Status** | Implemented · tested (mocked API) · deployed on Foundry `gpt-5-mini` |
| **Code** | [`narrative_engine/agents/`](../../narrative_engine/agents/): `llm.py`, `fake.py`, `prompts/` |
| **Libraries** | `agent-framework-core`, `agent-framework-openai`, `openai` |
| **Interface** | `summarise(variables)`, `compress(variables)`, `author(variables)` → `AgentResult` |
| **Tests** | `test_llm_agents.py` |

## 1. The three agents

*In short: two shared, neutral agents and one per-bucket author.*

| Agent | Runs | Prompt | Returns | Default effort |
| --- | --- | --- | --- | --- |
| `minute-summariser` | Once per closed minute with events | `minute-summary.v1` | JSON `{"summary": ...}` | minimal |
| `context-compressor` | When a compression rule fires | `context-compression.v1` | JSON `{"summary": ...}` | minimal |
| `narrative-author` | Once per bucket per step | `narrative-author.v2` | Plain text, one to three sentences | low |

Calls are stateless: each run gets a freshly built prompt and no conversation history (design principle 4). A summary reply that is not valid JSON gets one follow-up asking for the JSON only; an empty author reply is retried once.

## 2. How a call is made

*In short: Agent Framework agent → OpenAI chat completions client → Foundry's `/openai/v1` endpoint.*

1. `LLMAgents` builds one Agent Framework `Agent` per role, with a `default_options` `reasoning_effort` when set.
2. `chat_client()` creates the `OpenAIChatCompletionClient` on an `AsyncOpenAI` client. This is the only provider-specific code; change it to use another kind of model API.
3. The OpenAI client retries rate limits, server errors and dropped connections (4 retries). Auth failures fail at once.
4. Errors become `LLMError` with only the status code, never the response body, which can echo part of a key.
5. The result records the model that answered, the prompt version and token counts.

## 3. Model settings

*In short: `OPENAI_<SETTING>_<ROLE>` overrides `OPENAI_<SETTING>` for one role.*

| Setting | Variable | Per-role override |
| --- | --- | --- |
| Endpoint (includes `/v1`) | `OPENAI_BASE_URL` | `OPENAI_BASE_URL_AUTHOR`, `_SUMMARY`, `_COMPRESSION` |
| Key | `OPENAI_API_KEY` | `OPENAI_API_KEY_<ROLE>` |
| Model or deployment | `OPENAI_MODEL` | `OPENAI_MODEL_<ROLE>` |
| Reasoning effort | `OPENAI_EFFORT` (unset = not sent) | `OPENAI_EFFORT_<ROLE>` |

Example, a stronger author only: `OPENAI_MODEL_AUTHOR=gpt-5 OPENAI_EFFORT_AUTHOR=medium`. In Azure the same is done in Terraform ([deployment §3](../deployment.md#3-changing-a-model)).

Check the connection for all three roles: `python -m narrative_engine.agents.llm`.

## 4. Prompts

*In short: versioned runtime copies; the originals stay untouched.*

Runtime templates live in `agents/prompts/` with `{placeholder}` variables (JSON braces are left alone). Their first paragraphs keep the original wording from [design/example-prompts](../design/example-prompts/), which a test checks. A new version gets a new file name (`narrative-author.v2.txt`), and every block and narrative records the version that produced it. v2 of the author prompt stopped premature "final whistle" lines and invented xG.

## 5. Fakes (`fake.py`)

*In short: deterministic text with no model calls, for tests and offline runs.*

`FakeAgents` returns predictable summaries and narratives, records every call and its variables, and can delay the author to test concurrency. Select it with `AGENTS=fake` or `--agents fake`.
