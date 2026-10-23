# User backend documentation

> **In short:** the user backend serves the match viewer. It follows every live match from the stream, reads standard stats from ETL GraphQL, routes the narrative engine's bucket narratives, answers viewer questions with Microsoft Agent Framework agents and runs viewer-defined custom stats as bounded rules. It also serves story follows with moment clips, cross-game reach, the follow offer and (with `DEMO_SEEDS=1`) seed restore. Start with the overview, then the architecture; each component page maps to one code folder.

| | |
| --- | --- |
| **Status** | [overview](overview.md#3-status-by-area) |
| **Contracts** | [local/contracts/README.md](../../local/contracts/README.md) §1–8d |

Every page opens with an **In short** summary and a facts table, then numbered sections that each open with a one-line *In short*.

## Contents

```
docs/
├── README.md                 this index
├── overview.md               what the backend does, status, inputs and outputs, glossary
├── architecture.md           diagram, runtime flows, data model, service boundaries, scaling
├── components/               one page per code folder in user-backend/
│   ├── app.md                backend/app.py, store.py, domain.py: wiring and storage
│   ├── adapters.md           Event Hubs, Service Bus, ETL GraphQL, engine GraphQL, HLS, model and decision clients
│   ├── agents.md             question, replay, goal and follow-planner agents; compiler; data skill
│   ├── models.md             typed contracts: actions, events, rules, questions, audiences, config
│   ├── repositories.md       Postgres persistence per table group
│   ├── routes.md             every HTTP and WebSocket route
│   ├── services.md           live matches, gaps, filter engine, projections, questions, replays, follows, clips, cross-game
│   ├── demo.md               backend/demo/: demo-only seed export and restore
│   ├── migrations.md         Match App and Accounts schema, seeds, prompt seeds
│   ├── benchmarks.md         golden sets, corpora, model and filter benchmarks, measured results, doubles
│   ├── fixtures.md           fixtures/: the synthetic filter-lab match
│   └── devtools.md           devtools/ and backend/contracts/: the generated SPADL reference
├── development.md            local stack, configuration, tests, golden sets
├── deployment.md             Azure resources and what a production release still needs
├── decisions.md              design versus implementation, open items
├── narrative-framing.svg     service-boundary diagram (rendered by .github/scripts/render_architecture.py)
└── design/                   original plans, kept for history (not updated)
    ├── agreed-architecture.md      the original architecture agreement
    ├── question-agent-plan.md      the question-agent build plan
    ├── replay-plan.md              the chat-replay plan
    ├── custom-calculations.md      the proposed rule-worker design
    └── custom-calculations.svg     its diagram (rendered by the same script)
```

## Where to start

| If you want to… | Read |
| --- | --- |
| Understand the backend in five minutes | [overview.md](overview.md) |
| See how an event becomes a card, a narrative or an answer | [architecture.md](architecture.md) |
| Call the viewer, audience, prompt or developer APIs | [components/routes.md](components/routes.md) |
| Agree a contract with another service | [local/contracts/README.md](../../local/contracts/README.md) |
| Run it on your machine | [development.md](development.md), [../../DEVELOPMENT.md](../../DEVELOPMENT.md) |
| Deploy it | [deployment.md](deployment.md) |
| Know what differs from the original design and why | [decisions.md](decisions.md) |

## Code layout at a glance

| Folder | Contents | Page |
| --- | --- | --- |
| `backend/app.py`, `store.py`, `domain.py` | Composition root, Postgres pools and migrations, shared errors | [app](components/app.md) |
| `backend/adapters/` | Brokers, ETL and engine GraphQL, HLS, model and decision clients, feed reference | [adapters](components/adapters.md) |
| `backend/agents/` | Microsoft Agent Framework agents, workflow, compiler | [agents](components/agents.md) |
| `backend/models/` | Pydantic contracts | [models](components/models.md) |
| `backend/repositories/` | SQL per table group | [repositories](components/repositories.md) |
| `backend/routes/` | FastAPI routers | [routes](components/routes.md) |
| `backend/services/` | Application use cases and the rule engine | [services](components/services.md) |
| `backend/demo/` | Demo-only seed adapter (`DEMO_SEEDS=1`) | [demo](components/demo.md) |
| `migrations/` | Versioned SQL and data migrations, prompt seeds, demo profiles | [migrations](components/migrations.md) |
| `benchmarks/` | Golden sets, benchmarks, doubles and frozen results (never on the live path) | [benchmarks](components/benchmarks.md) |
| `fixtures/` | Synthetic test match | [fixtures](components/fixtures.md) |
| `devtools/`, `backend/contracts/` | SPADL reference generator and its output | [devtools](components/devtools.md) |
| `tests/` | Pytest suite against real Postgres; shared helpers in `harness.py` and `support.py` | [development](development.md#4-tests) |
| `Dockerfile` | `runtime` and `test` targets | [development](development.md#1-run-it) |
