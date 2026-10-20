# Narrative engine

![Shared match context becomes narratives for active audience buckets](architecture.svg)

**Implemented, tested and deployed to dev.** Turns the ETL's live match data into short narratives for up to 12 audience buckets (home, away or neutral × simple, casual, experienced or analyst), using Microsoft Agent Framework agents on Foundry. Narratives go to Cosmos DB, Service Bus and a history GraphQL API.

| | |
| --- | --- |
| **Documentation** | [docs/](docs/README.md): overview, architecture, one page per component, development, deployment, decisions |
| **For consumers** | [contracts/](contracts/README.md): history GraphQL, the `narratives` topic, the presence message |
| **Inputs** | [ETL contracts](../etl/contracts/README.md): Service Bus notifications and GraphQL |

```sh
cd narrative-engine && py -3.11 -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m pytest tests
.venv/Scripts/python -m narrative_engine.devtools.local tests/fixtures/itg-syn-0001-notifications.jsonl   # offline match, fake agents
```

| Folder | Contents |
| --- | --- |
| `narrative_engine/` | The service: `core/`, `context/`, `agents/`, `match_data/`, `store/`, `transport/`, `api.py`, `service.py`, `devtools/` |
| `contracts/` | What the user backend can rely on |
| `infra/` | Terraform for Azure dev |
| `tests/` | Pytest suite and synthetic fixtures |
| `docs/` | Documentation; original design material in `docs/design/` |
