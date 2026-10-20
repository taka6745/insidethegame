# Inside the Game

Live football, shared match narratives and a personal match companion.

![Five planned services and their data flows](architecture.svg)

**In build.** The ETL and the narrative engine are implemented, tested and deployed to a dev environment; the other services are at design stage. The diagrams describe the agreed build.

| Folder | What it does | Status |
| --- | --- | --- |
| [data-generation](data-generation/) | Prepare and replay an existing synthetic match into Event Hubs. | Design |
| [etl](etl/) | Store events, calculate match statistics and expose them through GraphQL. | Deployed (dev) · [docs](etl/docs/README.md) |
| [narrative-engine](narrative-engine/) | Build shared match memory and write narratives for up to 12 audience buckets. | Deployed (dev) · [docs](narrative-engine/docs/README.md) |
| [user-backend](user-backend/) | Answer questions, build custom stats and deliver each viewer's experience. | In progress |
| [frontend](frontend/) | Show the live match, stat cards, chat and narrative feed. | Design |

The demo has **one live match**, selectable profiles and one active session per profile. Viewer questions do not trigger narrative generation. Replay controls and semantic subscriptions are Phase 2.

Each folder has a short service guide and a closer diagram. Azure products are dependencies of these services, not additional application folders.

**Audience presence:** the narrative engine writes only for buckets the user backend reports as active, and for all 12 when presence is missing or stale. The message format awaits the user backend's agreement: [presence contract](narrative-engine/contracts/README.md#input-presence-proposed).

[Original Excalidraw board](legacy/design/plan.excalidraw) · [Archived research and simulator](legacy/README.md) · [Detailed user-backend decisions](user-backend/architecture.md)

Render the diagrams with `python3 .github/scripts/render_architecture.py`. Icons come from the preserved [engineering library](legacy/docs/icon-libraries/README.md); [attribution](.github/diagram-assets/README.md). Each implemented service deploys with its own Terraform (`<service>/infra/`); no CI is configured.
