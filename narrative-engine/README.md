# Narrative engine

[Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![Shared match context becomes narratives for active audience buckets](architecture.svg)

**Planned service; not implemented or deployed.** The retained [example prompts](prompts/README.md) are its only implementation inputs so far.

One minute summariser and context compressor build neutral, shared match memory. The author then writes for each active audience bucket: home, away or neutral × simple, casual, experienced or analytical. At most 12 buckets share the same facts; viewer questions never trigger this workflow.

| Component | Role in this design |
| --- | --- |
| Azure Container Apps | One Python orchestrator replica for the demo. |
| Microsoft Agent Framework SDK | Coordinate summariser, compressor and author agents. |
| Microsoft Foundry | Small model for summaries; stronger model for authoring. Exact deployments TBD. |
| Azure Cosmos DB | Context blocks, bucket narratives and match checkpoints. |
| Service Bus | Receive match/presence notifications; deliver new narratives to the user backend. |

**Input:** ETL GraphQL events, key-event ledger and statistics; match/presence notifications.

**Output:** bucket-tagged narratives and structured stat-selection instructions. New narratives travel through Service Bus. This service owns a GraphQL interface for narrative history; the user backend never reads Cosmos DB directly.

[Context and trigger rules](design-notes.md) · [Original design board](../legacy/design/plan.excalidraw) · [Repository plan](../README.md)
