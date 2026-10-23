# Narrative engine documentation

> **In short:** the narrative engine turns the ETL's live match data into short commentary ("narratives") for each audience bucket the user backend enables (team × fan style × length), stores it in Cosmos DB, publishes it on Service Bus and serves its history over GraphQL. Start with the overview, then the architecture; each component page maps to one code folder.

| | |
| --- | --- |
| **Status** | Implemented · tested · deployed ([overview](overview.md)) |
| **Models (Azure)** | `gpt-6.1-sol` (deployment `writer`, every agent at effort low) · Microsoft-Decision-1 (`decision-1`) |

Every page follows the same layout: an **In short** summary and a facts table at the top, then numbered sections that each open with a one-line *In short*.

## Contents

```
docs/
├── README.md              this index
├── overview.md            what the engine does, status, inputs and outputs, glossary
├── architecture.md        diagram, components, runtime flows, data model, Azure resources
├── components/            one page per code folder
│   ├── service.md         entry point: wires Service Bus, Cosmos DB, agents and the API
│   ├── core.md            match clock, messages, settings, the per-match orchestrator, audience targets
│   ├── analysis.md        analyst grounding, storylines, the author's grounding check
│   ├── context.md         shared match memory: compression, prompt text, prompt variables
│   ├── agents.md          Agent Framework agents, model settings, runtime prompts, fakes
│   ├── match-data.md      reading the ETL: GraphQL client (fixture double in tests/doubles)
│   ├── decisions.md       decision models (Decision-1, constrained-LLM fallback)
│   ├── follows.md         story follows: followed topics, trigger rules, follow narratives, moment clips
│   ├── store.md           Cosmos DB and in-memory stores
│   ├── transport.md       Service Bus, JSONL files, admin ASGI helpers
│   ├── api.md             narrative history GraphQL API
│   ├── demo.md            demo-only seed export/restore (DEMO_SEEDS)
│   ├── devtools.md        local runs, Azure dev helpers, HTML report, fixture tools
│   └── fixtures.md        authored commentary fixtures (backend tests, replay benchmark)
├── development.md         local setup, stand-ins for Azure, commands, tests
├── deployment.md          Terraform, image build, deploy, monitoring, costs
├── decisions.md           design versus implementation, open items
└── design/                original design material, kept for history
    ├── narrative-generation-engine.md   the detailed original design
    ├── design-notes.md                  context and trigger rules from the design board, audience ownership
    ├── implementation-plan.md           the phase-by-phase build plan and decision log
    ├── example-prompts/                 the board's original prompts, unchanged
    └── design-board.svg                 export of the board's narrative-engine section
```

## Where to start

| If you want to… | Read |
| --- | --- |
| Understand the service in five minutes | [overview.md](overview.md) |
| See how the parts fit and how a minute flows through | [architecture.md](architecture.md) |
| Consume narratives (user backend) | [../contracts/README.md](../contracts/README.md) |
| Run it on your machine | [development.md](development.md) |
| Run the whole product locally | [../../DEVELOPMENT.md](../../DEVELOPMENT.md) |
| Deploy or change a model | [deployment.md](deployment.md) |
| Know what differs from the original design and why | [decisions.md](decisions.md) |

## Code layout at a glance

| Folder | Contents | Page |
| --- | --- | --- |
| `narrative_engine/service.py` | The deployed service's entry point | [service](components/service.md) |
| `narrative_engine/core/` | Models, settings, orchestrator | [core](components/core.md) |
| `narrative_engine/audience/` | Audience targets from the user backend (one file) | [core §4](components/core.md#4-audience-targets) |
| `narrative_engine/analysis/` | Analyst grounding validator, storyline reducer, storyline policy | [analysis](components/analysis.md) |
| `narrative_engine/context/` | Compression, rendering, prompt variables | [context](components/context.md) |
| `narrative_engine/agents/` | Agent Framework agents and prompts | [agents](components/agents.md) |
| `narrative_engine/match_data/` | `MatchData` interface, ETL GraphQL client | [match-data](components/match-data.md) |
| `narrative_engine/decisions/` | Decision models (Microsoft-Decision-1, constrained-LLM fallback) | [decisions](components/decisions.md) |
| `narrative_engine/follows/` | Story follows: topics, trigger rules, steps | [follows](components/follows.md) |
| `narrative_engine/store/` | Cosmos DB, in-memory store | [store](components/store.md) |
| `narrative_engine/transport/` | Service Bus, JSONL files, admin ASGI helpers | [transport](components/transport.md) |
| `narrative_engine/api.py` | History GraphQL API | [api](components/api.md) |
| `narrative_engine/demo/` | Demo-only seed export/restore, mounted only with `DEMO_SEEDS=1` | [demo](components/demo.md) |
| `devtools/` | Developer commands and fixture tools (not deployed) | [devtools](components/devtools.md) |
| `fixtures/` | Authored commentary fixtures (backend tests and the replay benchmark); not part of the service | [fixtures](components/fixtures.md) |
| `contracts/` | What consumers can rely on | [contracts](../contracts/README.md) |
| `infra/` | Terraform for Azure dev | [deployment](deployment.md) |
| `tests/` | Pytest suite, test doubles (`doubles/`), shared helpers (`support.py`) and fixtures | [development](development.md#4-tests) |
