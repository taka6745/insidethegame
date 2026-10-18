# Microsoft Agent Framework agents

```text
Microsoft Agent Framework workflow
Question → goal agent → existing ETL stat, clarification, or custom goal
Custom goal → coding agent → structured rule → deterministic goal check
                 ↑                              │
                 └──── up to three repairs ─────┘
```

The coding agent writes the bounded rule DSL, never executable Python. The harness rejects missing or changed entity, event, operation and time constraints. It checks agreement with the goal; it cannot prove the language model interpreted every natural-language request correctly. Unsupported sequences, rolling windows and interpretive requests must be refused or clarified.

| Mode | Behaviour |
| --- | --- |
| `fixture` (default) | Exact sample phrases; no network or model calls. Other requests return unsupported. |
| `local` | Microsoft framework agents call the configured OpenAI-compatible development endpoint. Failures stay visible. |

Keep machine-specific settings in ignored `.local/backend-llm.env` (mode `600`):

```dotenv
LOCAL_LLM_MODE=local
LOCAL_LLM_BASE_URL=<development API base ending in /v1>
LOCAL_LLM_MODEL=<configured model or server-side fallback chain>
LOCAL_LLM_API_KEY=<local credential if required>
LOCAL_LLM_TIMEOUT_SECONDS=120
```

Never commit this file or log its contents. The model/chain choice is configuration; the adapter neither chooses providers nor changes server routing. Switch back to `fixture` to work without a model server. Restart the backend after changing environment values.

`backend/adapters/llm.py` creates Microsoft `Agent` instances with `OpenAIChatCompletionClient`. `agents/orchestrator.py` defines meaning; `agents/compiler.py` produces and validates rules. `agents/workflow.py` builds a real SDK `WorkflowBuilder` graph; `workflow_steps.py` owns its typed goal, generation and validation executors. Failed validation routes back to generation, with an initial attempt plus three repairs. Fixture mode runs the same graph with deterministic agent doubles.

Each request gets a fresh workflow and stateless agent calls. Only the typed goal and validation feedback pass between stages. SDK transport retries are disabled so application retry limits remain exact. The shared filter engine is plain deterministic Python; it never calls a model for each event. Views call services; agents never open databases.

Pinned dependencies: `agent-framework-core==1.22.0`, `agent-framework-openai==1.17.0`, and `openai==2.54.0` (the HTTP adapter uses the compatible httpx transport). No Azure account is needed for local mode. Foundry deployment remains a separate configuration/integration task. See Microsoft’s [workflow executors](https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/executors) and [running agents](https://learn.microsoft.com/en-us/agent-framework/agents/running-agents) documentation.

Tests use scripted responses, including incorrect-but-valid rules, repairs, exhaustion, unknown entities, unavailable models and standard-stat reuse. Live model calls are optional development checks, not part of the repeatable suite.

Goal definition retries once for transient failures or invalid output. Coding allows an initial attempt plus three repairs. Both stages share a 150-second deadline; authentication failures stop immediately in either agent. Diagnostic logs contain only failure categories/status codes, never model response bodies or credentials.
