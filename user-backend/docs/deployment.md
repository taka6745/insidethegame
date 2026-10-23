# Deployment

> **In short:** a Container App in the shared Azure Container Apps environment, with Azure Database for PostgreSQL, secrets in Key Vault read by a managed identity, and Azure AI Foundry (Azure OpenAI) for questions. Defined in the root [`terraform/`](../../terraform/) (`./dev azure up`, [runbook](../../terraform/docs/deployment.md)).

| | |
| --- | --- |
| **Status** | Deployed with Terraform (mock-tested in CI) · the demo build sets `DEMO_SEEDS=1`, `--release` leaves it off |
| **Terraform** | [`terraform/`](../../terraform/) (`backend.tf`, `databases.tf`, `keyvault.tf`, `foundry.tf`) |
| **Image** | `user-backend/Dockerfile`, target `runtime`, pushed to the shared (ETL) registry as `user-backend:<tag>` |
| **Ingress** | Internal only; the frontend's nginx (`/viewer-api/`) and the engine call it |

## 1. Resources

*In short: one app, one database server, one model deployment.*

| Resource | Use |
| --- | --- |
| Container App `itgdemo-backend` (0.5 vCPU, 1 replica, always on) | The API; readiness `/ready`, liveness TCP |
| PostgreSQL Flexible Server B1ms | `accounts`, `matchapp` (TLS; Azure services only) |
| Key Vault + user-assigned identity | Database URLs, Event Hubs and Service Bus keys, Foundry key, Decision-1 key |
| Foundry deployment `questions` (`gpt-6.1-sol`, 130K TPM, effort low) on the engine's account | Question, goal, replay and follow-planner agents; with `LOCAL_LLM_EFFORT` they use the Responses API with a reasoning effort and no temperature (`adapters/llm.py`). `/dev/config/models` can point a role at another deployment on the same endpoint |
| The engine's Microsoft-Decision-1 deployment | The follow offer's yes/no (`DECISION_BASE_URL`, `DECISION_MODEL`, key in Key Vault) |
| From `etl/infra` | Event Hubs consumer group `user-backend` (key `user-backend-listen`), DAB GraphQL |
| From `narrative-engine/infra` | Service Bus `narratives` subscription `user-backend`, engine GraphQL |
| From `data-generation/infra` | `FEED_HLS_BASE`: the feed's internal HLS origin |

## 2. Settings in Azure

*In short: the same variables as Compose.*

`LOCAL_LLM_BASE_URL` is the Foundry Azure OpenAI v1 endpoint, `LOCAL_LLM_MODEL` the deployment and `LOCAL_LLM_API_KEY` its key (Key Vault). `ENABLE_DEV_FEED` and `ENABLE_FILTER_LAB` follow `dev_admin`; the backend is internal and nginx puts those routes behind basic auth. `DEMO_SEEDS` follows `demo_seeds` (on for the demo build; `./dev azure up --release` turns it off); demo control calls the seed routes over internal ingress. `DECISION_*` points at the engine's Decision-1 deployment.

## 3. Before a production release

*In short: the gaps that remain.*

- Managed identities with RBAC instead of keys; private endpoints (needs a VNet environment); protected remote state.
- Authentication and per-account quotas for questions.
- Projections, takeover, gap buffers and fan-out are process-local, so more than one replica needs fenced match ownership and shared delivery ([architecture §6](architecture.md#6-scaling-boundary)).

The repository-wide checklist is [terraform/docs/decisions.md](../../terraform/docs/decisions.md#2-before-a-production-release).
