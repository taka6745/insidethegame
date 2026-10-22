# Deployment

> **In short:** a Container App in the shared Azure Container Apps environment, with Azure Database for PostgreSQL, secrets in Key Vault read by a managed identity, and Azure AI Foundry (Azure OpenAI) for questions. Defined in the root [`terraform/`](../../terraform/) (`./dev azure up`, [runbook](../../terraform/runbook.md)); applied 22 Oct for the Azure test, acceptance (PLAN.md §10.4) pending.

| | |
| --- | --- |
| **Status** | Terraform implemented, mock-tested and planned · applied 22 Oct (Azure test) · judge build sets `DEMO_SEEDS=1` |
| **Terraform** | [`terraform/`](../../terraform/) (`backend.tf`, `databases.tf`, `keyvault.tf`, `foundry.tf`) |
| **Image** | `user-backend/Dockerfile`, target `runtime`, pushed to the shared (ETL) registry as `user-backend:<tag>` |
| **Ingress** | Internal only; the frontend's nginx (`/viewer-api/`) and the engine call it |

## 1. Resources

*In short: one app, one database server, one model deployment.*

| Resource | Use |
| --- | --- |
| Container App `itgdemo-backend` (0.5 vCPU, 1 replica, always on) | The API; readiness `/ready`, liveness TCP |
| PostgreSQL Flexible Server B1ms | `accounts`, `matchapp` (TLS; Azure services only) |
| Key Vault + user-assigned identity | Database URLs, Event Hubs and Service Bus keys, Foundry key |
| Foundry deployment `questions` (`gpt-6.1-sol`) on the engine's account | Question, goal, replay and follow-planner agents; `LOCAL_LLM_EFFORT` makes them send `reasoning_effort` and no temperature (`adapters/llm.py` `chat_options`) |
| From `etl/infra` | Event Hubs consumer group `user-backend` (key `user-backend-listen`), DAB GraphQL |
| From `narrative-engine/infra` | Service Bus `narratives` subscription `user-backend`, engine GraphQL |
| From `data-generation/infra` | `FEED_HLS_BASE`: the feed's internal HLS origin |

## 2. Settings in Azure

*In short: the same variables as Compose.*

`LOCAL_LLM_BASE_URL` is the Foundry Azure OpenAI v1 endpoint, `LOCAL_LLM_MODEL` the deployment and `LOCAL_LLM_API_KEY` its key (Key Vault). `ENABLE_DEV_FEED` and `ENABLE_FILTER_LAB` follow `dev_admin`; the backend is internal and nginx puts those routes behind basic auth. `DEMO_SEEDS` follows `demo_seeds` (on for the judge build; `./dev azure up --release` turns it off); demo control calls the seed routes over internal ingress. No `DECISION_*` is set here, so on Azure the follow offer's yes/no runs on the `questions` deployment.

## 3. Before a production release

*In short: the gaps that remain.*

- Managed identities with RBAC instead of keys; private endpoints (needs a VNet environment); protected remote state.
- Authentication and per-account quotas for questions.
- Projections, takeover, gap buffers and fan-out are process-local, so more than one replica needs fenced match ownership and shared delivery ([architecture §6](architecture.md#6-scaling-boundary)).

The repository-wide checklist is [terraform/deployment-readiness.md](../../terraform/deployment-readiness.md).
