# Deployment

> **In short:** Terraform in `infra/` creates the engine's Azure resources next to the ETL's; the image is built locally and pushed, then a second apply deploys it. Models are chosen per agent in Terraform, and Application Insights shows what the agents are doing.

| | |
| --- | --- |
| **Status** | Applied 22 Oct by `./dev azure up` for the Azure test ([runbook](../../terraform/runbook.md)); `decision-1` applied, the `writer` switch to `gpt-6.1-sol` is in Terraform but not yet in the applied state; demo acceptance (PLAN.md §10.4) pending |
| **Models** | `writer` = Azure OpenAI `gpt-6.1-sol` (GlobalStandard, 200K TPM; every agent at effort `low`, its lowest) · `decision-1` = Microsoft-Decision-1 (DataZoneStandard, 50 requests/minute) |
| **Demo build** | `demo_seeds` sets `DEMO_SEEDS=1`; `./dev azure up` turns it on for the judge build, `./dev azure up --release` turns it off ([service §5](components/service.md#5-demo-seeds-demo_seeds)) |
| **Terraform** | [`infra/`](../infra/), local state, reads the ETL's state for its Service Bus namespace and Container Apps environment |
| **Region** | Australia East |
| **Cost when idle** | About US$10–20/month (Container App always on, registry); models and Cosmos are pay per use |

## 1. Infrastructure

*In short: one file per concern.*

| File | Creates |
| --- | --- |
| `main.tf` | Resource group, budget alert, naming |
| `cosmos.tf` | Serverless Cosmos DB, database `narrative`, eight containers (checkpoints, contextBlocks, narratives, analyses, storylines, subscriptionDecisions, subscriptionNarratives, tombstones), your data role |
| `messaging.tf` | Topic `narratives` (subscriptions `user-backend`, `narrative-check`), scoped keys |
| `foundry.tf` | Azure AI Foundry account and one deployment per entry in `models`: `writer` (Azure OpenAI `gpt-6.1-sol`) for the agents and `decision-1` (Microsoft-Decision-1, DataZoneStandard, 50 requests/minute) for story follows and claim checks (`var.decision`; the app gets `DECISION_*` on the same account) |
| `app.tf` | Container registry, Container App (secrets, settings including `DEMO_SEEDS` from `demo_seeds`, identity), Cosmos role for the app |
| `monitoring.tf` | Log Analytics workspace, Application Insights, the "Narrative engine" workbook |
| `variables.tf`, `outputs.tf`, `versions.tf` | Inputs, outputs (secrets marked sensitive), providers |

## 2. Deploying

*In short: apply, build, apply again with the image tag.*

```sh
cd narrative-engine
cp infra/local.auto.tfvars.example infra/local.auto.tfvars      # subscription and budget emails
terraform -chdir=infra init
terraform -chdir=infra apply                                    # everything except the app
.venv/Scripts/python -m narrative_engine.devtools.azure build --tag v4 --local
terraform -chdir=infra apply -var engine_image_tag=v4 -var user_backend_url=<backend url>
```

- `user_backend_url` is required: the engine reads audience targets and prompts there and has no fallback. The ETL subscription keeps old replays; purge them (`POST /admin/matches/purge`, internal) rather than narrating them.
- Trial subscription limits shape this: one Container Apps environment per region (so the engine uses the ETL's), no ACR Tasks (so `--local`), and a Contributor role that cannot create role assignments (so keys instead of managed identity, except for Cosmos).
- Providers that had to be registered once: `Microsoft.CognitiveServices`, `Microsoft.ContainerRegistry`, `Microsoft.Insights`.

## 3. Changing a model

*In short: add a deployment, point an agent at it, apply.*

```hcl
# infra/local.auto.tfvars (or -var)
models = {
  "writer" = { model = "gpt-6.1-sol", version = "2026-09-29", capacity = 200 }
  "gpt-5"      = { version = "<version>", capacity = 50 }
}
agents = {
  summary     = { model = "writer", effort = "low" }
  compression = { model = "writer", effort = "low" }
  analyst     = { model = "writer", effort = "low" }
  author      = { model = "gpt-5", effort = "medium" }
}
```

Terraform creates the deployment and sets `OPENAI_MODEL_AUTHOR` and `OPENAI_EFFORT_AUTHOR` on the app. Every narrative records its model, so the report can compare runs. Models that are not OpenAI format take `format` and `sku` in `models`; a different API altogether means changing `chat_client()` in [agents](components/agents.md#2-how-a-call-is-made).

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
