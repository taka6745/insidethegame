# Azure infrastructure

`./dev azure` manages the application. Use [Docker](../local/README.md) for daily development; cloud deployment is separate.

![Application architecture](../architecture.svg)

## Commands

| From the repository root | Does |
| --- | --- |
| `./dev terraform check` | Format, validate and mock-test all stacks; no cloud calls |
| `./dev azure plan` / `status` | Preview changes / inspect resources |
| `./dev azure up --release` | Apply application stacks, build images, upload media and start Stream Analytics |

**Confirm with the developer before any apply.** Requires Docker, `az login` with suitable permissions, FFmpeg and Foundry quota. Secrets, state and tfvars stay ignored. Stop Stream Analytics after testing: `cd etl && python3 -m devtools asa stop`.

`up` rewrites the [edge proxy](../edge-proxy/README.md) upstream; redeploy that Worker separately.

## Application stacks

| Stack | Owns |
| --- | --- |
| [ETL](../etl/infra/) | Brokers, SQL, DAB, ETL apps, shared Container Apps environment and registry |
| [Narrative](../narrative-engine/infra/) | Foundry, Cosmos, engine and narrative topic |
| [Feed](../data-generation/infra/) | Provider app, PostgreSQL and Blob Storage |
| [Application](./) | Backend, frontend, Key Vault and question deployment |

Australia East; only the frontend has public ingress. The [deployment driver](azure/azure.py) reads local state under `.local/terraform/`; its tests run with `cd terraform/azure && python3 -m unittest test_azure -v`.

## Status

See [root Status](../README.md#status) for deployment verification and open checks.

## Decisions and production gaps

One shared Container Apps environment; host-built images; keys in Key Vault or app secrets. Before production: private networking, managed identities/RBAC, least-privilege database users, protected remote Terraform state, authentication and quotas, and [coordinated replicas](../user-backend/README.md#limits). Emulators and mock plans do not prove cloud security, durability or capacity.
