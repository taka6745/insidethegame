# Azure infrastructure

> **In short:** the whole stack in Terraform. Five stacks; `./dev azure up` applies them in order and `./dev azure down` removes them, keeping the spend guard. Daily development uses [Docker Compose](../local/README.md). [Docs](docs/README.md).

| Terraform | Owns |
| --- | --- |
| [`guard/`](guard/) | Budgets (email only), Stream Analytics start/stop runbook, the last resort at 90 % of the credit |
| [`etl/infra/`](../etl/infra/) | Event Hubs, Stream Analytics (+ its event-driven schedule), Azure SQL, Data API builder, purge API, Service Bus `match-notifications`, the shared Container Apps environment and registry |
| [`narrative-engine/infra/`](../narrative-engine/infra/) | Azure AI Foundry (`writer`, `gpt-6-luna`, `gpt-5-mini`, `Microsoft-Decision-1`), Cosmos DB, engine app, Service Bus `narratives`, monitoring |
| [`data-generation/infra/`](../data-generation/infra/) | The simulated provider (feed): its own resource group, PostgreSQL, Blob Storage, app |
| `terraform/` (this folder) | User backend, demo control, frontend, seeds share (demo build), backend PostgreSQL, Key Vault, the backend's Foundry deployment (`questions`) |

```sh
./dev terraform check   # fmt, validate, fmt and validate all five; mock tests for app, guard and feed; no Azure calls
./dev azure plan        # real plan against your subscription (az login); applies nothing
./dev azure up          # deploy everything (asks first); see docs/deployment.md
```

Confirm with the developer before any apply; never commit state or tfvars.
