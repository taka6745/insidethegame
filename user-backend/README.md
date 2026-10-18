# User backend

[Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![Questions, custom calculations and personalised delivery](architecture.svg)

**Planned service.** Owns profiles, sessions, questions, stat cards and narrative routing. It does not generate the shared game narrative.

| Component | Role |
| --- | --- |
| Azure Container Apps | Python API, agents, shared calculations and live delivery. |
| Microsoft Agent Framework + Foundry | Question agent defines the goal; coding agent writes and tests a function. Models TBD. |
| Azure PostgreSQL Flexible Server | Accounts and Match App databases on one server. |
| Isolated executor | Fixed Python libraries; controlled read-only GraphQL. Sandbox technology TBD. |

**Read:** live events from Event Hubs; historical events and computed stats from ETL GraphQL; narrative history from narrative GraphQL; new narratives and stat-selection instructions through Service Bus.

**Deliver:** answers, stat values and existing bucket narratives through the API and one live connection per session. Publish active-bucket presence changes for the narrative engine; questions never drive narrative generation.

Custom stats follow **goal → write → test → calculate → optional pin**. Allow up to three repairs. Equivalent requests share one match-scoped calculation. A pin replaces the lowest-priority default stat; it is a live card, not an alert.

One active session per demo profile. Restore chat and pins on reconnect; a new tab takes over. Phase 2 adds Jev subscriptions, clip resolution and playback-aware state.

[Full decisions and acceptance scenarios](architecture.md) · [Repository plan](../README.md)
