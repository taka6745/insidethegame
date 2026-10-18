# Inside the Game

Live football, shared match narratives and a personal match companion.

![Five planned services and their data flows](architecture.svg)

**Runnable development lab.** Build custom filters from a request or preset, then watch synthetic match events update shared calculations. Python agents, an indexed rule engine, Postgres and a small browser UI run locally. Production messaging and the full viewer experience remain to build. These diagrams describe the agreed application design.

**[Start developing →](DEVELOPMENT.md)** · [Development practices](DEVELOPMENT-PRACTICES.md) · [Local Docker setup](local/README.md) · [Terraform](terraform/README.md)

```sh
./dev up backend
```

Open the [event filter lab](http://localhost:18020). Load a JSON recording or use the included demo, pick filters, then replay and inspect each event and live value. [How it works](user-backend/docs/filter-lab.md).

| Folder | What it does |
| --- | --- |
| [data-generation](data-generation/) | Prepare and replay an existing synthetic match into Event Hubs. |
| [etl](etl/) | Store events, calculate match statistics and expose them through GraphQL. |
| [narrative-engine](narrative-engine/) | Build shared match memory and write narratives for every available DB-defined audience bucket. |
| [user-backend](user-backend/) | Answer questions, build custom stats and deliver each viewer's experience. |
| [frontend](frontend/) | Show the live match, stat cards, chat and narrative feed. |

The demo has **one live match**, selectable profiles and one active session per profile. Viewer questions do not trigger narrative generation. Replay controls and semantic subscriptions are Phase 2.

Each folder has a short service guide and a closer diagram. Azure products are dependencies of these services, not additional application folders.

**Narrative boundary:** the backend exposes bucket definitions through a read-only API; the narrative engine owns framing. The backend receives finished bucket versions and routes them. [Diagram and current implementation](user-backend/docs/narrative-framing.md).

[Original Excalidraw board](legacy/design/plan.excalidraw) · [Archived research and simulator](legacy/README.md) · [Detailed user-backend decisions](user-backend/architecture.md)

Render the diagrams with `python3 .github/scripts/render_architecture.py`. Icons come from the preserved [engineering library](legacy/docs/icon-libraries/README.md); [attribution](.github/diagram-assets/README.md). No cloud deployment or CI is configured.
