# User backend documentation

> **In short:** the user backend serves the match viewer. It follows every live match from the stream, reads standard stats from ETL GraphQL, routes the narrative engine's bucket narratives, answers viewer questions with Microsoft Agent Framework agents and runs viewer-defined custom stats as bounded rules. For the demo it serves story follows with moment clips, cross-game reach, the follow offer and (with `DEMO_SEEDS=1`) seed restore. Start with the overview, then the architecture; each component page maps to one code folder.

| | |
| --- | --- |
| **Status** | Implemented · tested (601 on Postgres) · D1–D7 on the local stack 22 Oct · Azure applied 22 Oct, acceptance pending |
| **Contracts** | [local/contracts.md](../../local/contracts.md) §1–8c |

Every page follows the same layout: an **In short** summary and a facts table at the top, then numbered sections that each open with a one-line *In short*.

## Contents

```
docs/
├── README.md                 this index
├── overview.md               what the backend does, status, inputs and outputs, glossary
├── architecture.md           diagram, runtime flows, data model, service boundaries, scaling
├── components/               one page per code folder in user-backend/
│   ├── app.md                backend/app.py, store.py, domain.py: wiring and storage
│   ├── adapters.md           Event Hubs, Service Bus, ETL GraphQL, engine GraphQL, HLS, model client
│   ├── agents.md             question, replay and goal agents; compiler; data skill
│   ├── models.md             typed contracts: events, rules, questions, audiences, config
│   ├── repositories.md       Postgres persistence per table group
│   ├── routes.md             every HTTP and WebSocket route, including the audience and prompt APIs
│   ├── services.md           live matches, gaps, filter engine, projections, questions, replays, follows, clips, cross-game, seeds
│   ├── migrations.md         Match App and Accounts schema, seeds, prompt seeds
│   └── benchmarks.md         golden sets, model and filter benchmarks, test fixtures
├── development.md            local stack, configuration, tests, golden sets
├── deployment.md             Azure target and what is still missing
├── decisions.md              design versus implementation, open items
├── narrative-framing.svg     service-boundary diagram (rendered by .github/scripts/render_architecture.py)
├── custom-calculations.svg   historical rule-worker diagram (same script)
└── design/                   original plans, kept for history (not updated)
    ├── agreed-architecture.md      the 18 October 2026 architecture agreement
    ├── question-agent-plan.md      the question-agent build plan
    ├── question-readiness.md       an 18 October readiness snapshot
    ├── replay-plan.md              the chat-replay plan
    └── custom-calculations.md      the proposed rule-worker design (+ ../custom-calculations.svg)
```

## Where to start

| If you want to… | Read |
| --- | --- |
| Understand the backend in five minutes | [overview.md](overview.md) |
| See how an event becomes a card, a narrative or an answer | [architecture.md](architecture.md) |
| Call the viewer, audience, prompt or developer APIs | [components/routes.md](components/routes.md) |
| Agree a contract with another service | [local/contracts.md](../../local/contracts.md) |
| Run it on your machine | [development.md](development.md), [../../DEVELOPMENT.md](../../DEVELOPMENT.md) |
| Deploy it | [deployment.md](deployment.md) |
| Know what differs from the original design and why | [decisions.md](decisions.md) |

## Code layout at a glance

| Folder | Contents | Page |
| --- | --- | --- |
| `backend/app.py`, `store.py`, `domain.py` | Composition root, Postgres pools and migrations, shared errors | [app](components/app.md) |
| `backend/adapters/` | Brokers, ETL and engine GraphQL, HLS, model client, feed reference | [adapters](components/adapters.md) |
| `backend/agents/` | Microsoft Agent Framework agents, workflow, compiler | [agents](components/agents.md) |
| `backend/models/` | Pydantic contracts | [models](components/models.md) |
| `backend/repositories/` | SQL per table group | [repositories](components/repositories.md) |
| `backend/routes/` | FastAPI routers | [routes](components/routes.md) |
| `backend/services/` | Application use cases and the rule engine | [services](components/services.md) |
| `backend/demo/` | Demo-only seed adapter (`DEMO_SEEDS=1`) | [services §11](components/services.md#11-demo-seeds) |
| `migrations/` | Versioned SQL, prompt seeds, demo profiles | [migrations](components/migrations.md) |
| `benchmarks/`, `fixtures/` | Golden sets, benchmarks and test doubles (never on the live path) | [benchmarks](components/benchmarks.md) |
| `tests/` | Pytest suite against real Postgres | [development](development.md#4-tests) |
| `Dockerfile` | `runtime` and `test` targets | [development](development.md#1-run-it) |
