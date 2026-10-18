# Develop shared narratives

![Service boundary](../architecture.svg)

**Own:** neutral match memory, neutral narratives, narrative history and deduplication. Questions never start this workflow.

```text
Notification + match GraphQL → memory → neutral author
                                ↓          ↓
                             Cosmos    Service Bus + history API
```

**Start:** [Docker setup](../../DEVELOPMENT.md), then `./dev test` for Cosmos or `./dev test azure` for messaging. Local tests create `narrative/{contextBlocks,narratives,checkpoints}`, partitioned by `/matchId`.

**Build next:** Python orchestrator using Microsoft Agent Framework; implement the [summary/compression rules](../design-notes.md). Keep original [prompts](../prompts/README.md) intact. Resolve text-vs-JSON outputs before wiring the author. Publish neutral sources with stable IDs/revisions and separate approved stat selections; expose owned GraphQL history.

**Prove it:** repeat a notification without duplicate output; recover checkpoints; exclude superseded summaries; keep independent match context; preserve neutral facts and evidence. Use labelled deterministic model fixtures for tests, then run a separate real-model check.

**Azure:** Container Apps, Foundry, Cosmos and Service Bus. Foundry requires a real configured model endpoint; no LLM is emulated here. The backend frames every configured bucket without sending presence feedback. Never read the backend's user database.
