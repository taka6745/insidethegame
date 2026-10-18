# Microsoft Agent Framework agents

```text
Microsoft Agent Framework workflow
Question → goal agent → existing ETL stat, clarification, or custom goal
Custom goal → deterministic DSL compiler → goal/rule validation
Clarification → viewer reply → goal agent (original request preserved)
```

The default local path compiles the typed goal into a bounded rule DSL without another model call. The optional model-based coding agent remains available for experiments with the same validation and repair budget. Neither path executes generated Python. The harness rejects missing or changed entity, event, operation and time constraints. It checks agreement with the goal; it cannot prove the language model interpreted every natural-language request correctly. Unsupported sequences, rolling windows and interpretive requests must be refused or clarified.

| Mode | Behaviour |
| --- | --- |
| `fixture` (default) | Exact sample phrases; no network or model calls. Other requests return unsupported. |
| `local` | A Microsoft framework goal agent calls the configured OpenAI-compatible development endpoint; compilation is deterministic. Failures stay visible. |

Keep machine-specific settings in ignored `.local/backend-llm.env` (mode `600`):

```dotenv
LOCAL_LLM_MODE=local
LOCAL_LLM_BASE_URL=<development API base ending in /v1>
LOCAL_LLM_MODEL=<configured model or server-side fallback chain>
LOCAL_LLM_API_KEY=<local credential if required>
LOCAL_LLM_TIMEOUT_SECONDS=60
AGENT_PLAN_TIMEOUT_SECONDS=60
AGENT_MAX_REPAIRS=3
AGENT_GOAL_OUTPUT_MODE=prompt
```

Never commit this file or log its contents. The model/chain choice is configuration; the adapter neither chooses providers nor changes server routing. Switch back to `fixture` to work without a model server. Restart the backend after changing environment values.

`backend/adapters/llm.py` creates Microsoft `Agent` instances with `OpenAIChatCompletionClient`. `agents/orchestrator.py` defines meaning; `agents/compiler.py` produces and validates rules. `agents/workflow.py` builds a real SDK `WorkflowBuilder` graph; `workflow_steps.py` owns its typed goal, generation and validation executors. Failed validation routes back to compilation/generation, with an initial attempt plus three repairs. The local default normally makes one successful model call per turn; a transient or schema failure can add one goal retry. Fixture mode runs the same graph with deterministic agent doubles.

Each request gets a fresh workflow and stateless agent calls. The server supplies bounded prior user/assistant messages on clarification or correction turns. Only the typed goal and validation feedback pass to compilation. Event history, fixture expectations and future events are never sent to the goal agent. SDK transport retries are disabled so application retry limits remain exact. The shared filter engine is plain deterministic Python; it never calls a model for each event. Views call services; agents never open databases.

Pinned dependencies: `agent-framework-core==1.22.0`, `agent-framework-openai==1.17.0`, and `openai==2.54.0` (the HTTP adapter uses the compatible httpx transport). No Azure account is needed for local mode. Foundry deployment remains a separate configuration/integration task. See Microsoft’s [workflow executors](https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/executors) and [running agents](https://learn.microsoft.com/en-us/agent-framework/agents/running-agents) documentation.

Tests use scripted responses, including incorrect-but-valid rules, repairs, exhaustion, unknown entities, unavailable models and standard-stat reuse. Live model calls are optional development checks, not part of the repeatable suite.

Goal definition retries once for transient failures or invalid output. Coding allows an initial attempt plus three repairs. All stages share `AGENT_PLAN_TIMEOUT_SECONDS` (default 60 seconds, configurable 1–300) per turn; authentication failures stop immediately in either agent. Diagnostic logs contain only failure categories/status codes, never model response bodies or credentials.

`AGENT_MAX_REPAIRS` is the backend-wide coding repair budget (0–20, default 3), excluding the initial attempt. Compose sets it at the backend service level; override with `AGENT_MAX_REPAIRS=5 ./dev up backend`. Invalid values fail startup. Goal definition still has one transient retry and the overall deadline still applies. [Opt-in agent evaluation and algorithm benchmarks](../benchmarks/README.md) are separate from pytest.

The goal schema enumerates supported events and outcomes; feed semantics define headed contacts, shot attempts, half boundaries and strict/inclusive time windows. `PlanOutcome` reports model-call count and stage timings. These help diagnose latency; goal validation still does not prove the user’s meaning was understood. The separate evaluation checks known intentions and values independently.

In default `prompt` mode, the model-facing contract inlines schema references and omits titles/default annotations while preserving types, enums, bounds and required fields. Four decision shapes make nesting explicit. `goal_failure_reasons` records safe retry categories; `goal_validation_errors` adds bounded attempt/field-path/error-type details, masking unknown extra keys. Neither records rejected values or provider error text. A timeout leaves these diagnostics `null` when the workflow cannot recover them.

Optional **`AGENT_GOAL_OUTPUT_MODE=schema`** passes the generated JSON Schema through Microsoft Agent Framework's [`response_format` option](https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs). The SDK requests strict JSON output; the same schema goes in model context. Each response must also pass strict local JSON-type validation and the existing cross-field checks. Provider rejection stays visible; there is no automatic downgrade. Keep `prompt` as the default until the chosen route supports the complete contract reliably. A simple schema canary is insufficient: routes may accept a small schema but reject or ignore a larger one.

```text
Typed Goal / Clarification models
        ↓ generated contract
SDK response_format + model context → strict local validation
                                             ↓
                                    goal → compiler → rule checks
```

The schema is generated from the current typed models, not maintained as a second hand-written list. Changing a field updates the contract on the next process start; tests check new fields, bounds, defaults and inherited validators. Every strict wire field is required: `[]` means unrestricted arrays, `null` means unused nullable constraints. Contract/prompt hashes in evaluations identify the exact version tested. Deploy code and contract together and rerun the relevant gold cases and provider compatibility checks. Future nested model fields and arbitrary-key maps fail contract construction until explicitly supported, preventing provider/local validation drift. New operators still need compiler/executor support and tests; changing a schema alone cannot add a capability. Vendor feed-key changes belong in the event adapter, which preserves the internal event model.

**A valid schema does not prove correct meaning.** A model can emit a perfectly valid first-half restriction the viewer never requested. Keep semantic gold tests, clarification checks and model-strength comparisons separate from format checks. [Measured schema study](../benchmarks/results/schema-study.md).

For model selection, use the [pinned-model comparison](../benchmarks/README.md#compare-pinned-models-and-prompt-variants). It checks reported model identities, prompt/schema hashes, clarification outcomes, tokens and latency. A fallback chain is not a fixed model; a provider's model name is evidence of routing, not independent verification of its weights. Keep routing choices in the ignored configuration and inspect the [measured comparison](../benchmarks/results/model-strength.md) before choosing a smaller model.

A narrow first-turn check asks which player an unresolved “his” or “her” refers to without spending a model call. It does not infer or repair the metric. Follow-up answers preserve the full request and displayed options; the model must retain earlier constraints unless the viewer explicitly changes them. This remains evaluated language understanding, not a guarantee against semantic mistakes.

Lab continuation: `POST /lab/plan` accepts `prompt` and optional `conversation_id`. The server keeps the transcript; clients cannot inject assistant messages. Conversations are bounded and ephemeral, not durable or authenticated production sessions. See [the lab guide](filter-lab.md).
