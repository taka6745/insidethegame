# Narrative engine

[Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![Shared match context becomes narratives for active audience buckets](architecture.svg)

**Runnable demo stub; production agents remain planned.** The stub owns authored commentary for the recorded synthetic match and factual neutral recap history. It never calls an LLM. The original [prompts](prompts/README.md) are preserved for the real implementation.

Authored [fixtures](fixtures/README.md) (schema v2) cover the 90-minute broadcast-clock recording: 92 minutes × 12 buckets, minute/tier recaps and key moments.

```text
Service Bus checkpoint → neutral recap archive → GraphQL → user backend
                       ↓
Authored commentary + enabled audiences → Service Bus → user backend
```

The backend owns audience definitions; this service reads its `generation_targets` and returns those already-framed versions unchanged. Questions read neutral context and never author narratives. Events and standard statistics remain ETL-owned.

| Demo now | Planned replacement |
| --- | --- |
| Python/FastAPI service | Container Apps orchestrator |
| Authored match-specific commentary | Agent Framework + Foundry author |
| Deterministic factual recap tiers | Summariser/compressor agents |
| SQLite archive, owned by this service | Cosmos DB |
| Service Bus notifications/live delivery + GraphQL history | Production producers and durable Azure storage |

Run locally: `pip install -r requirements-dev.txt`, then `python -m pytest` or `uvicorn narrative_demo.app:from_env --factory --port 18030`. Set ETL, audience and storage paths as described in the guide. The authored stub now uses the real Service Bus SDK against local emulators. It remains a single-process demo, not a production narrative engine. HTTP checkpoint mode remains available for isolated fixture tests.
