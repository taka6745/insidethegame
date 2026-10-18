# Narrative engine

[Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![Shared match context becomes narratives for active audience buckets](architecture.svg)

**Runnable demo stub; production agents remain planned.** The stub owns authored commentary for the recorded synthetic match and factual neutral recap history. It never calls an LLM. The original [prompts](prompts/README.md) are preserved for the real implementation.

```text
ETL checkpoint → neutral recap archive → GraphQL → user backend
                       ↓
Authored match commentary + enabled audiences → bucket narratives
```

The backend owns audience definitions; this service reads its `generation_targets` and returns those already-framed versions unchanged. Questions read neutral context and never author narratives. Events and standard statistics remain ETL-owned.

| Demo now | Planned replacement |
| --- | --- |
| Python/FastAPI service | Container Apps orchestrator |
| Authored match-specific commentary | Agent Framework + Foundry author |
| Deterministic factual recap tiers | Summariser/compressor agents |
| SQLite archive, owned by this service | Cosmos DB |
| Checkpoint HTTP + GraphQL reads | Notifications + Service Bus live delivery; GraphQL history |

Run locally: `pip install -r requirements-dev.txt`, then `python -m pytest` or `uvicorn narrative_demo.app:from_env --factory --port 18030`. Set ETL, audience and storage paths as described in the guide. The demo is not a production narrative engine or a broker durability test.
