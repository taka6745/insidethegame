# Frontend

> **In short:** the match viewer, filter lab and `/dev/` console as static TypeScript modules behind nginx. Viewers press **Start demo**, watch three live matches (the main game opens first), ask questions, follow stories in this or another match, and play captured clips with a sting and slow motion.

| | |
| --- | --- |
| **Status** | See [overview](docs/overview.md) |
| **Public URL** | `https://msft-hackathon.koda-software.com` ([edge proxy](../edge-proxy/README.md) → the Azure frontend) |
| **Talks to** | `/viewer-api/` (backend), `/demo-api/` (demo control), `/media/hls/` (feed); developer consoles gated |
| **Run** | `ACCEPT_EULA=Y ./dev up backend`, then `http://localhost:18020/` ([development](docs/development.md)) |

[Docs](docs/README.md) · [Overview](docs/overview.md) · [Architecture](docs/architecture.md) · [Development](docs/development.md) · [Deployment](docs/deployment.md)

![Live match, statistics and two conversation tabs](architecture.svg)

```text
Static HTML / CSS / modules ← nginx (or a CDN)
             ↓ one live connection
User backend → match state + cards + narratives
             ↔ questions + Track / Untrack + follows
Demo control ↔ Start / Cancel / Skip ahead
```

The browser never calculates statistics, runs a model or reads a database; one push connection per viewer and a shared projection per match avoid per-viewer polling. The local stack is not a viewer-capacity demonstration ([production boundary](docs/decisions.md#2-production-boundary)).

[Repository plan](../README.md)
