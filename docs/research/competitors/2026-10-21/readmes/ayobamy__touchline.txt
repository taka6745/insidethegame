# Touchline

**AI agents that explain the game as it happens, in your language, for your club.**

Touchline is a live match producer made of AI agents. It turns a stream of synthetic football events into explained, verified, timed overlays that sit on screen beside the match, and personalizes them for each viewer: an analyst gets full metrics in English, while a casual fan gets plain-language explanations in Nigerian Pidgin, following one player if they like.

Built for the Microsoft *Inside the Game: Developer Hackathon* (October 2026). All data is synthetic, and all clubs and players are fictional.

## How it works

One pipeline, five stages:

| Stage | What happens | Status |
| --- | --- | --- |
| 1. Ingest | A steerable match simulator streams passes, shots, tackles, pressure and possession changes | Built |
| 2. Interpret | A deterministic stats engine computes pass difficulty, xG, speeds, possession, momentum, pressure index, chaos and rhythm; rules flag candidate moments; an MCP server exposes it all to agents | Built |
| 3. Explain | Four agents decide what matters, explain why, and verify every claim against the tools and event IDs; templates cover any agent that fails | Orchestrator built with recorded model replies; Microsoft Foundry next |
| 4. Render | Timed overlay JSON is pushed to a live pitch view | Contract built, UI planned |
| 5. Personalize | Role, club, player, language and favourite metric shape what each viewer sees | Planned |

The core rule: **the code computes every number; the AI only explains them.** Every overlay must cite the events behind it, or it is rejected.

## Quick start

The data pipeline needs Go 1.24 or later and nothing else. The agents need Python 3.12 or later.

```bash
# Generate a match as newline-delimited JSON
go run ./cmd/simulator -seed 7 > match.ndjson

# Replay a scenario at one match minute per second and watch the stats move
go run ./cmd/simulator -seed 7 -scenario scenarios/late-press.json -speed 60 \
  | go run ./cmd/stats -every 5 -pretty

# Serve a live match to agents over MCP (http://localhost:8080/mcp);
# the API reference is at http://localhost:8080/docs
go run ./cmd/server -simulate -seed 7 -scenario scenarios/late-press.json -speed 60

# Run the four agents over a replayed match with recorded model replies (no Azure needed)
make agents

# Run the tests
make test          # Go
make agents-test   # Python: lint, types, tests
```

The same seed and scenario always produce the same match, so a demo can be replayed exactly.

## Scenarios

| File | Story |
| --- | --- |
| `scenarios/baseline.json` | An even match |
| `scenarios/late-press.json` | Ironbridge Rovers press high from the hour mark |
| `scenarios/red-card.json` | Riverside Athletic go down to ten men on 58 minutes |

Scenarios shift probabilities; they never fix the result.

## Repository layout

```
cmd/simulator      synthetic match generator (NDJSON to stdout or a file)
cmd/stats          reads a stream, prints statistics snapshots
cmd/server         replays a match and serves it as MCP tools and a JSON API
internal/events    event, match and stream contract
internal/sim       the simulator and scenarios
internal/stats     deterministic metrics and the running stats engine
internal/moments   rules that flag candidate moments for the agents
internal/store     live match state, safe for concurrent readers
internal/mcp       a small, dependency-free MCP server (stdio and HTTP)
internal/mcptools  the Touchline tools agents call
internal/overlay   the on-screen overlay contract and its validation
internal/apidocs   the OpenAPI document and the API reference at /docs
schema/            JSON Schemas for events, matches and overlays
scenarios/         scenario files
docs/              plan, architecture, contracts, implementation guide
agents/            the agent orchestrator, agent instructions and tests (Python)
web/               pitch view and overlays (planned)
```

## Documentation

Start with [docs/README.md](docs/README.md). Highlights:

- [Overview](docs/01-overview.md): the problem, the users and how Touchline meets the brief
- [Plan](docs/02-plan.md): the 13-day build plan, milestones and risks
- [Architecture](docs/03-architecture.md): components, data flow and Azure services
- [Data contracts](docs/04-data-contracts.md): events, matches and overlays
- [Stats engine](docs/05-stats-engine.md): every metric and its formula
- [Agents](docs/06-agents.md): roles, shared state, handoffs and failure recovery
- [Implementation guide](docs/07-implementation.md): how to build, test and deploy each part
- [Architecture decisions](docs/adr/README.md): why things are the way they are

## Built with

Go, Python, Model Context Protocol (our own Go server and the official Python SDK), Scalar, Microsoft Foundry, Microsoft Agent Framework, Azure Event Hubs, Azure Container Apps, Azure SignalR Service and Azure Managed Redis. The Azure and Foundry parts are planned; the status table above shows what exists today.

## Licence

MIT. See [LICENSE](LICENSE).
