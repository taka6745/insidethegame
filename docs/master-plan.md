# Master plan

[Editable board](../master-plan.excalidraw) · [SVG](../master-plan.svg)

[Independent review record](reviews/master-plan-2026-10-19.md)

This is the **target design**, checked against the original board's detailed sections and later service decisions. It does not describe deployment readiness or claim measured production capacity.

| Boundary | Agreed responsibility |
| --- | --- |
| Feed → Event Hubs | A simulated external provider replays synthetic matches (several at once, one `matchId` each) on the video's timeline. ETL and the backend consume independently. |
| ETL | Stream Analytics; Azure SQL event history, key-event ledger and standard stats (`statsAtSeq`; the earlier Cosmos DB stats store was dropped on 20 October 2026). Data API builder GraphQL is the read boundary. |
| ETL → narratives | Publish readiness/triggers only after the corresponding history and stats are readable. |
| Backend | Reuse standard stats; answer questions; validate and share custom rules/results; persist user state in PostgreSQL. |
| Generated code | Structured rules use the bounded compiler/index. The planned Python/regex path uses a separate isolated executor with fixed libraries and a controlled read-only GraphQL helper. |
| Narrative engine | Shared neutral recap memory, upstream deduplication, enabled-bucket framing and stat-selection instructions. Persist before Service Bus publication; GraphQL provides retained recap/history versions. |
| Audience configuration | Backend-owned layers/options/semantic descriptions. Narrative generation reads enabled combinations; questions never trigger this workflow. |
| Frontend | Five live cards, chat and unchanged bucket narratives. One active viewer session; live is forward-only; chat clip replays are allowed. |

Grey marks Phase 2: semantic follows and question-agent web search. Replay playlists, HLS streaming and data held to the picture moved into the current plan on 20 October 2026 ([replay plan](../user-backend/docs/design/replay-plan.md)) and are implemented and tested locally. The isolated executor is a planned capability, not an agreed Phase 2 feature. The current bounded-rule implementation does not execute generated Python.

“Commit + notify” is a logical consistency requirement, not a chosen Azure product or a cross-database transaction. Production watermark coordination, recovery/outbox handling, worker leases, managed fan-out transport and model deployments still need implementation decisions. The backend's live custom-event path does not wait for ETL's database writes; historical backfill must reconcile event IDs/revisions and its starting watermark with that live path.

The compact board abbreviates recap compaction and author triggers; [exact rules](../narrative-engine/docs/design/design-notes.md) remain authoritative. All recap versions stay available, while default context uses only non-superseded coverage. Standard card names shown in the frontend are illustrative: ranked IDs from the narrative engine choose the actual cards.

Sources: [original detailed board](../legacy/design/plan.excalidraw), [backend decisions](../user-backend/docs/decisions.md), [ETL](../etl/README.md), [narrative rules](../narrative-engine/docs/design/design-notes.md), [audience API](../user-backend/docs/components/routes.md#3-audience-configuration).
