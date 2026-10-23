# Narrative engine

> **In short:** turns the ETL's live match data into short narratives for the user backend's active audience buckets, using Microsoft Agent Framework agents on Azure AI Foundry and Microsoft-Decision-1 for claim checks, story-follow triggers and moment clips. Narratives go to Cosmos DB, Service Bus and a history GraphQL API. Implemented and tested ([status](docs/overview.md)).

[Documentation](docs/README.md) · [Shared local setup](../DEVELOPMENT.md)

![Shared match context becomes narratives for active audience buckets](architecture.svg)

Locally it runs as **`narrative-live`** in the shared Docker stack (`./dev up backend`): any number of matches under one model-call limit, each purged on its own. Without the user backend it pauses and reports unhealthy rather than falling back.

| | |
| --- | --- |
| **Documentation** | [docs/](docs/README.md): overview, architecture, one page per component, development, deployment, decisions |
| **For consumers** | [contracts/](contracts/README.md): history GraphQL, the `narratives` topic, targets and prompts from the user backend |
| **Inputs** | [ETL contracts](../etl/contracts/README.md): Service Bus notifications and GraphQL |

```sh
cd narrative-engine && python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
.venv/bin/python -m devtools.local tests/fixtures/itg-syn-0001-notifications.jsonl   # offline match, fake agents
```

| Folder | Contents |
| --- | --- |
| `narrative_engine/` | The engine: `core/`, `context/`, `agents/`, `analysis/`, `audience/`, `decisions/`, `follows/`, `match_data/`, `store/`, `transport/`, `demo/`, `api.py`, `service.py` |
| `devtools/` | Developer commands and fixture tools (not deployed) |
| `contracts/` | What the user backend can rely on |
| `infra/` | Terraform for Azure |
| `tests/` | Pytest suite, test doubles (`tests/doubles/`) and synthetic fixtures |
| `fixtures/` | [Authored commentary fixtures](docs/components/fixtures.md) for backend tests and the replay benchmark; not part of the service |
| `docs/` | Documentation; original design material in `docs/design/` |
