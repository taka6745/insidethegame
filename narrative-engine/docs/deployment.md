# Deployment

> **In short:** Terraform in `infra/` creates the engine's Azure resources next to the ETL's; the image is built locally and pushed, then a second apply deploys it. Models are chosen per agent in Terraform, and Application Insights shows what the agents are doing.

| | |
| --- | --- |
| **Status** | Applied with every service by `./dev azure up` ([runbook](../../terraform/docs/deployment.md)); Azure status: [PLAN §11](../../PLAN.md#11-azure-judge-build) |
| **Models** | `writer` = Azure OpenAI `gpt-6.1-sol` (GlobalStandard, 120K TPM; every agent at effort `low`, its lowest) · `decision-1` = Microsoft-Decision-1 (DataZoneStandard, 50 requests/minute) |
| **Demo build** | `demo_seeds` sets `DEMO_SEEDS=1`; `./dev azure up` turns it on for the demo build, `./dev azure up --release` turns it off ([demo](components/demo.md)) |
| **Terraform** | [`infra/`](../infra/), local state, reads the ETL's state for its Service Bus namespace and Container Apps environment |
| **Region** | Australia East |
| **Cost when idle** | About 10–20/month, billing currency (Container App always on, registry); models and Cosmos are pay per use |

## 1. Infrastructure

*In short: one file per concern.*

| File | Creates |
| --- | --- |
| `main.tf` | Resource group, budget alert, naming |
| `cosmos.tf` | Serverless Cosmos DB, database `narrative`, eight containers (checkpoints, contextBlocks, narratives, analyses, storylines, subscriptionDecisions, subscriptionNarratives, tombstones), your data role |
| `messaging.tf` | Topic `narratives` (subscriptions `user-backend`, `narrative-check`), scoped keys |
| `foundry.tf` | Azure AI Foundry account and one deployment per entry in `models`: `writer` (Azure OpenAI `gpt-6.1-sol`) for the agents, the alternates `gpt-6-luna` and `gpt-5-mini`, and `decision-1` (Microsoft-Decision-1, DataZoneStandard, 50 requests/minute) for story follows and claim checks (`var.decision`; the app gets `DECISION_*` on the same account) |
| `app.tf` | Container registry, Container App (secrets, settings including `DEMO_SEEDS` from `demo_seeds`, identity), Cosmos role for the app |
| `monitoring.tf` | Log Analytics workspace, Application Insights, the "Narrative engine" workbook |
| `variables.tf`, `outputs.tf`, `versions.tf` | Inputs, outputs (secrets marked sensitive), providers |

| Resource | Name (dev) | Notes |
| --- | --- | --- |
| Resource group | `rg-itg-narrative-dev` | Budget alert at 20/month (billing currency, A$) |
| Container App | `itg-narrative-dev-engine` | 0.5 vCPU, 1 GiB, 1 replica, internal ingress on 8000 (only the backend, the frontend's dev purge proxy and demo control call it); `DEMO_SEEDS=1` on the demo build; in the ETL's environment (one per region on the trial) |
| Container Registry | `itgnarrativedevdhcyoacr` | Basic; images built locally and pushed |
| Cosmos DB | `itg-narrative-dev-dhcyo-cosmos` | Serverless; engine uses managed identity |
| Azure AI Foundry (AI Services) | `itg-narrative-dev-dhcyo-foundry` | Deployments in Terraform `models`: `writer` (`gpt-6.1-sol`, every agent at effort low) and `decision-1` (Microsoft-Decision-1, 50 requests/minute), plus the switchable alternatives `gpt-6-luna` and `gpt-5-mini` (100K TPM each); the user backend adds its own `questions` deployment here |
| Service Bus topic | `narratives` | In the ETL namespace; subscriptions `user-backend`, `narrative-check`. The engine reads `match-notifications` through the ETL's `narrative-engine` subscription |
| Application Insights | `itg-narrative-dev-dhcyo-appi` | Own Log Analytics workspace (0.2 GB/day cap); workbook "Narrative engine" |

## 2. Deploying

*In short: apply, build, apply again with the image tag.*

```sh
cd narrative-engine
cp infra/local.auto.tfvars.example infra/local.auto.tfvars      # subscription and budget emails
terraform -chdir=infra init
terraform -chdir=infra apply                                    # everything except the app
.venv/bin/python -m devtools.azure build --tag v4 --local
terraform -chdir=infra apply -var engine_image_tag=v4 -var user_backend_url=<backend url>
```

- `user_backend_url` is required: the engine reads audience targets and prompts there and has no fallback. The ETL subscription keeps old replays; purge them (`POST /admin/matches/purge`, internal) rather than narrating them.
- Trial subscription limits shape this: one Container Apps environment per region (so the engine uses the ETL's), no ACR Tasks (so `--local`), and a Contributor role that cannot create role assignments (so keys instead of managed identity, except for Cosmos).
- Providers that had to be registered once: `Microsoft.CognitiveServices`, `Microsoft.ContainerRegistry`, `Microsoft.Insights`.

## 3. Changing a model

*In short: switch live under `/dev/config/models` ([agents §3](components/agents.md#3-model-settings)), or add a deployment, point an agent at it and apply.*

The alternates `gpt-6-luna` and `gpt-5-mini` are already deployed. To make a role's model permanent:

```hcl
# infra/local.auto.tfvars (or -var)
agents = {
  summary     = { model = "writer", effort = "low" }
  compression = { model = "writer", effort = "low" }
  analyst     = { model = "writer", effort = "low" }
  author      = { model = "gpt-6-luna", effort = "medium" }
}
```

A new model is an entry in `models` (keep the defaults beside it). Terraform sets `OPENAI_MODEL_AUTHOR` and `OPENAI_EFFORT_AUTHOR` on the app. Every narrative records its model, so the report can compare runs. Models that are not OpenAI format take `format` and `sku` in `models`; a different API altogether means changing `chat_client()` in [agents](components/agents.md#2-how-a-call-is-made).

## 4. Monitoring

*In short: Application Insights `{name_prefix}-{suffix}-appi` (e.g. `itg-narrative-dev-xxxxx-appi`), with a ready-made workbook.*

| Where (portal) | Shows |
| --- | --- |
| Workbooks → **Narrative engine** | Agent runs, latency and tokens per agent, narratives per minute, failures, warnings |
| Investigate → **Search**, `invoke_agent` | One agent run end to end, with its model call |
| Investigate → **Performance** → Dependencies | Slowest operations |
| Investigate → **Failures** | Failed calls with exceptions |
| Monitoring → **Logs** | Your own queries (`dependencies`, `traces`) |

Data arrives 2–5 minutes late and is kept 30 days. Traces are sampled, so counts use `sum(itemCount)`. Exact token totals are on every block and narrative in Cosmos. Set `ENABLE_SENSITIVE_DATA=true` on the app to include prompts and replies.

## 5. Operating

*In short: the few things to remember.*

| Task | How |
| --- | --- |
| See a match's output | `devtools.azure report --match-id X` |
| Check delivery | `devtools.azure check-narratives --match-id X` |
| Choose buckets | Enable buckets in the user backend at `user_backend_url` (`/dev/`); the engine reads its `audience-config` |
| Container logs | `az containerapp logs show -n itg-narrative-dev-engine -g rg-itg-narrative-dev --tail 50` |
| Restart safely | Any time; live matches resume from their checkpoints |
| Live test | Start the ETL's Stream Analytics job, replay a match, then **stop the job** (it bills while running) |
