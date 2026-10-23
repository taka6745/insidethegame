# User backend

> **In short:** serves the match viewer for every live match: cards from ETL GraphQL stats, the narrative engine's bucket narratives, grounded answers from Microsoft Agent Framework agents, custom stats as bounded rules over ETL's SPADL actions, replay clips from the feed's HLS, story follows with moment clips, cross-game reach and the "Follow this story?" offer.

![Questions, custom calculations and personalised delivery](architecture.svg)

| | |
| --- | --- |
| **Status** | Implemented, tested on real Postgres with contract doubles, deployed on Azure ([overview](docs/overview.md#3-status-by-area)) |
| **Reads** | Event Hubs `match-events`, ETL GraphQL (DAB), narrative GraphQL + Service Bus `narratives`, feed HLS |
| **Serves** | `/product` viewer API + WebSocket, audience, prompt, policy and model-role APIs for the engine, `/dev` and `/lab` |
| **Models** | Azure: `gpt-6.1-sol` deployment `questions` (effort low), switchable per role under `/dev/config/models`; follow offers on Microsoft-Decision-1 (`DECISION_*`) |
| **Demo only** | `DEMO_SEEDS=1` mounts seed export/restore ([demo seeds](docs/components/demo.md)) |

```sh
ACCEPT_EULA=Y ./dev up backend
./dev demo start
./dev test backend
```

[Documentation](docs/README.md) · [Architecture](docs/architecture.md) · [APIs](docs/components/routes.md) · [Development](docs/development.md) · [Benchmarks](docs/components/benchmarks.md) · [Contracts](../local/contracts/README.md) · [API explorer](http://localhost:18000/docs) · [Filter lab](http://localhost:18020/lab/) · [Developer config](http://localhost:18020/dev/)
