# User backend

[Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![Questions, custom calculations and personalised delivery](architecture.svg)

**Runnable foundation.** Profiles, sessions, stat cards and bucket routing work against Postgres, the standalone demo ETL and the authored narrative stub. Live events and narratives now use the Microsoft Event Hubs/Service Bus emulators; GraphQL supplies history and standard stats. Test doubles remain for isolated tests. The [filter lab](docs/filter-lab.md) adds Microsoft Agent Framework goal/coding agents and workflows, structured custom rules and shared indexed calculations. The [Questions tab](docs/question-agent.md) adds short grounded match answers, neutral recap reads and one-off custom stat offers. This service does not generate the shared game narrative.

```sh
ACCEPT_EULA=Y ./dev up backend
./dev reset backend
./dev replay backend
```

[Filter lab](http://localhost:18020/lab/) · [API explorer](http://localhost:18000/docs) · [Test coverage](docs/testing.md) · [Synthetic examples](fixtures/filter-lab.md)

The diagram and components below describe the target architecture; the [development guide](docs/development.md) separates implemented behaviour from fixtures.

| Component | Role |
| --- | --- |
| Azure Container Apps | Python API, agents, shared calculations and live delivery. |
| Microsoft Agent Framework + Foundry | Goal agent interprets/clarifies; deterministic compiler builds bounded rules. Foundry deployment planned. |
| Azure PostgreSQL Flexible Server | Accounts and Match App databases on one server. |
| Isolated executor | Fixed Python libraries; controlled read-only GraphQL. Sandbox technology TBD. |

**Standard stats:** ETL computes and stores them (PostgreSQL in the demo; Cosmos DB planned). Fetch values through ETL GraphQL, then select/rank/deliver. Agents query the same API for specific historical events from ETL-owned storage. Custom calculations are only for requests that existing ETL stats cannot answer.

**Read:** live events from Event Hubs; historical events and computed stats from ETL GraphQL; narrative history from narrative GraphQL; new narratives and stat-selection instructions through Service Bus.

**Deliver:** answers, stat values and existing bucket narratives through the API and one live connection per session. Audience definitions are exposed through the [configuration API](docs/audience-api.md); framing belongs to the narrative engine; questions never drive narrative generation. [Connection boundary](docs/narrative-framing.md).

Custom stats follow **interpret / clarify → compile → validate → calculate → optional pin**. The local default uses one successful model call per turn; the model-based rule coder remains optional. Allow `AGENT_MAX_REPAIRS` repairs (default 3). Equivalent requests share one match-scoped calculation. A pin replaces the lowest-priority default stat; it is a live card, not an alert.

One active session per demo profile. Restore chat and pins on reconnect; a new tab takes over. The viewer chooses any of three match allegiances and four styles independently. Connected combinations enable narrative generation targets in PostgreSQL; all twelve definitions remain stored. Phase 2 adds Jev subscriptions. Chat replay clips are implemented: a specialist replay agent picks evidence IDs and code cuts VOD playlists ([replay](docs/replay-plan.md)).

[Composite metrics and follow-up choices](docs/composite-metrics.md) · [Custom-rule storage and execution](docs/custom-calculations.md) · [Full decisions and acceptance scenarios](architecture.md) · [Repository plan](../README.md)

[Opt-in correctness and performance harness](benchmarks/README.md): 100 hand-authored stat cases plus negative prompts; 100–100m unique-filter stress tiers, bounded by time and memory. Excluded from normal pytest.
