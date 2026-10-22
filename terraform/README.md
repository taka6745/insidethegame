# Azure infrastructure

> **In short:** the whole stack in Terraform, **applied 22 Oct** for the Azure test (acceptance pending). Five stacks; `./dev azure up` applies them in order and `./dev azure down` removes them, keeping the spend guard ([runbook](runbook.md)). Daily development uses [Docker Compose](../local/README.md).

| Terraform | Owns | Status |
| --- | --- | --- |
| [`guard/`](guard/) | Budgets (email only), Stream Analytics start/stop runbook, the last resort at 90 % of the credit | Applied 22 Oct |
| [`etl/infra/`](../etl/infra/) | Event Hubs, Stream Analytics (+ its event-driven schedule), Azure SQL, Data API builder, purge API, Service Bus `match-notifications`, the shared Container Apps environment and registry | Applied 22 Oct |
| [`narrative-engine/infra/`](../narrative-engine/infra/) | Azure AI Foundry (`gpt-6.1-sol` `writer`, `Microsoft-Decision-1`), Cosmos DB, engine app, Service Bus `narratives`, monitoring | Applied 22 Oct (Decision-1; `writer` rollout pending) |
| [`data-generation/infra/`](../data-generation/infra/) | The simulated provider (feed): its own resource group, PostgreSQL, Blob Storage, app | Applied 22 Oct |
| `terraform/` (this folder) | User backend, demo control, frontend, seeds share (judge build), backend PostgreSQL (`accounts`, `matchapp`), Key Vault, the backend's Foundry deployment (`gpt-6.1-sol` `questions`) | Applied 22 Oct (`questions` rollout pending) |

```sh
./dev terraform check   # fmt, validate, mock tests for all five; no Azure calls
./dev azure plan        # real plan against your subscription (az login); applies nothing
```

```text
browser ─▶ edge proxy (Cloudflare) ─▶ frontend (nginx, public) ─┬▶ /viewer-api → backend (internal) ─▶ Postgres, Key Vault, Foundry
                                                                ├▶ /demo-api   → demo control (internal) ─▶ feed, ETL, engine, backend; seeds share
                                                                └▶ /media/hls  → feed (internal, its own RG) ─▶ Blob Storage
feed ─▶ Event Hubs ─▶ Stream Analytics ─▶ Azure SQL ─▶ DAB (internal) ─▶ backend, engine (internal)
                       └▶ Service Bus ─▶ engine (Foundry, Cosmos) ─▶ narratives ─▶ backend
```

This folder reads the other stacks' outputs from their local state (`*_state_path`). The backend's secrets live in Key Vault, read by its user-assigned identity; the developer consoles sit behind basic auth (`dev_admin`, on by default). See [deployment readiness](deployment-readiness.md) for what remains before a production release. Confirm with the developer before any apply; never commit state or tfvars.
