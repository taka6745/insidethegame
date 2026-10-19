# Inside the Game

Live football, shared match narratives and a personal match companion.

![Five planned services and their data flows](architecture.svg)

**[Master architecture — editable Excalidraw](master-plan.excalidraw)** · [Full graphical plan](master-plan.svg). GRF/ETL left, backend and narrative engine centre, frontend right; Phase 2 in grey.

**Runnable development lab.** Build custom filters from a request or preset, then watch synthetic match events update shared calculations. Python agents, an indexed rule engine, Postgres and a small browser UI run locally. The match viewer adds live cards, bucketed insights and questions; live messaging uses Microsoft emulators; cloud deployment remains to build. These diagrams describe the agreed application design.

**[Start developing →](DEVELOPMENT.md)** · [Development practices](DEVELOPMENT-PRACTICES.md) · [Local Docker setup](local/README.md) · [Terraform](terraform/README.md)

```sh
ACCEPT_EULA=Y ./dev up backend
```

Open the [match viewer](http://localhost:18020) for the Chelsea–Manchester United demo, or the [event filter lab](http://localhost:18020/lab/). Pick filters, then replay and inspect each event and live value. The connected demo recording is managed by ETL; standalone lab mode also supports JSON uploads. [How it works](user-backend/docs/filter-lab.md).

| Folder | What it does |
| --- | --- |
| [data-generation](data-generation/) | Prepare and replay an existing synthetic match into Event Hubs. |
| [etl](etl/) | Store events, calculate match statistics and expose them through GraphQL. |
| [narrative-engine](narrative-engine/) | Build shared match memory and write narratives for every available DB-defined audience bucket. |
| [user-backend](user-backend/) | Answer questions, build custom stats and deliver each viewer's experience. |
| [frontend](frontend/) | Show the live match, stat cards, chat and narrative feed. |

The demo has **one live match**, selectable profiles and one active session per profile. Viewer questions do not trigger narrative generation. Replay controls and semantic subscriptions are Phase 2.

Each folder has a short service guide and a closer diagram. Azure products are dependencies of these services, not additional application folders.

**Event paths:** Event Hubs streams independently to ETL and the backend's custom filters. Live backend events do not pass through a database. Historical events and computed standard stats come from ETL GraphQL.

**Narrative boundary:** the backend exposes bucket definitions through a read-only API; the narrative engine owns framing. The backend receives finished bucket versions and routes them. [Diagram and current implementation](user-backend/docs/narrative-framing.md).

[Original Excalidraw board](legacy/design/plan.excalidraw) · [Archived research and simulator](legacy/README.md) · [Detailed user-backend decisions](user-backend/architecture.md)

[Review results](docs/reviews/2026-10-19.md) · [Hackathon readiness](docs/reviews/hackathon-readiness.md) · [Azure deployment gaps](terraform/deployment-readiness.md)

Render the diagrams with `python3 .github/scripts/render_architecture.py`. Icons come from the preserved [engineering library](legacy/docs/icon-libraries/README.md); [attribution](.github/diagram-assets/README.md). No cloud deployment or CI is configured.

The master board is generated with `python3 .github/scripts/render_master_plan.py`. Its shapes, labels, connectors and embedded icons are editable in Excalidraw. Regenerating replaces manual edits, so keep a copy before doing that. Export `master-plan.svg` through the Excalidraw CLI after updates. The original board remains preserved in `legacy/design/`.
