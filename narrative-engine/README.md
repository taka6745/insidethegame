# Narrative engine

[Documentation](docs/README.md) · [Shared local setup](../DEVELOPMENT.md)

![Shared match context becomes narratives for active audience buckets](architecture.svg)

**Implemented and tested; applied to Azure on 22 Oct for the Azure test (demo acceptance pending).** Turns the ETL's live match data into short narratives for the user backend's active audience buckets (by default home, away or neutral × simple, casual, experienced or analyst), using Microsoft Agent Framework agents on **Azure AI Foundry** (Azure OpenAI `gpt-6.1-sol` as deployment `writer`, effort low; in Terraform, not yet in the applied state) and **Microsoft-Decision-1** for claim checks, story-follow triggers and moment clips. Narratives go to Cosmos DB, Service Bus and a history GraphQL API.

The shared local Docker stack runs this engine as **`narrative-live`** (`./dev up backend`): the local ETL stream's notifications in, the local model, the backend's enabled buckets and prompts per matchId, Cosmos emulator, live narratives to the viewer (history GraphQL on `127.0.0.1:18012`). Any number of matches run at once under one model-call limit; each is purged on its own (`POST /admin/matches/purge`). Without the backend it pauses and reports unhealthy rather than falling back. Remaining items: [decisions](docs/decisions.md#3-open-items).

**Demo build (PLAN.md §10, built 22 Oct; unit-tested and checked on the local stack, not yet on Azure):** moment clips for follows (`FollowClip`, D3/D6) and for shared key-event narratives (`MomentClip`, D7); seed export/restore for mid-match starts (D2), mounted only with `DEMO_SEEDS=1` ([service](docs/components/service.md#5-demo-seeds-demo_seeds)).

| | |
| --- | --- |
| **Documentation** | [docs/](docs/README.md): overview, architecture, one page per component, development, deployment, decisions |
| **For consumers** | [contracts/](contracts/README.md): history GraphQL, the `narratives` topic, targets and prompts from the user backend |
| **Inputs** | [ETL contracts](../etl/contracts/README.md): Service Bus notifications and GraphQL |

```sh
cd narrative-engine && py -3.11 -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
PYTHONUTF8=1 .venv/Scripts/python -m pytest tests
.venv/Scripts/python -m narrative_engine.devtools.local tests/fixtures/itg-syn-0001-notifications.jsonl   # offline match, fake agents
```

| Folder | Contents |
| --- | --- |
| `narrative_engine/` | The engine: `core/`, `context/`, `agents/`, `match_data/`, `store/`, `transport/`, `api.py`, `service.py`, `devtools/` |
| `contracts/` | What the user backend can rely on |
| `infra/` | Terraform for Azure dev |
| `tests/` | Pytest suite and synthetic fixtures |
| `docs/` | Documentation; original design material in `docs/design/` |
| `fixtures/`, `tools/` | [Authored commentary fixtures](fixtures/README.md) for backend tests and the replay benchmark; not part of the service |
