# Deployment

> **In short:** Terraform in `infra/` creates the engine's Azure resources next to the ETL's; the image is built locally and pushed, then a second apply deploys it. Models are chosen per agent in Terraform, and Application Insights shows what the agents are doing.

| | |
| --- | --- |
| **Status** | Deployed to dev (image `v3`) |
| **Terraform** | [`infra/`](../infra/), local state, reads the ETL's state for its Service Bus namespace and Container Apps environment |
| **Region** | Australia East |
| **Cost when idle** | About US$10–20/month (Container App always on, registry); models and Cosmos are pay per use |

## 1. Infrastructure

*In short: one file per concern.*

| File | Creates |
| --- | --- |
| `main.tf` | Resource group, budget alert, naming |
| `cosmos.tf` | Serverless Cosmos DB, database `narrative`, three containers, your data role |
| `messaging.tf` | Topics `narratives` (subscriptions `user-backend`, `narrative-check`) and `presence` (subscription `narrative-engine`), scoped keys |
| `foundry.tf` | Foundry account and one deployment per entry in `models` |
| `app.tf` | Container registry, Container App (secrets, settings, identity), Cosmos role for the app |
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
terraform -chdir=infra apply -var engine_image_tag=v4 -var match_ids=<matchId>
```

- `match_ids` limits which matches the deployed engine narrates. Keep it set: the ETL subscription keeps old replays, and an empty value narrates all of them.
- Trial subscription limits shape this: one Container Apps environment per region (so the engine uses the ETL's), no ACR Tasks (so `--local`), and a Contributor role that cannot create role assignments (so keys instead of managed identity, except for Cosmos).
- Providers that had to be registered once: `Microsoft.CognitiveServices`, `Microsoft.ContainerRegistry`, `Microsoft.Insights`.

## 3. Changing a model

*In short: add a deployment, point an agent at it, apply.*

```hcl
# infra/local.auto.tfvars (or -var)
models = {
  "gpt-5-mini" = { version = "2025-08-07", capacity = 100 }
  "gpt-5"      = { version = "<version>", capacity = 50 }
}
agents = {
  summary     = { model = "gpt-5-mini", effort = "minimal" }
  compression = { model = "gpt-5-mini", effort = "minimal" }
  author      = { model = "gpt-5", effort = "medium" }
}
```

Terraform creates the deployment and sets `OPENAI_MODEL_AUTHOR` and `OPENAI_EFFORT_AUTHOR` on the app. Every narrative records its model, so the report can compare runs. Models that are not OpenAI format take `format` and `sku` in `models`; a different API altogether means changing `chat_client()` in [agents](components/agents.md#2-how-a-call-is-made).

## 4. Monitoring

*In short: Application Insights `itg-narrative-dev-dhcyo-appi`, with a ready-made workbook.*

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
| Simulate viewers | `devtools.azure send-presence --match-id X --counts '{"home:casual": 2}' --minutes 20` |
| Container logs | `az containerapp logs show -n itg-narrative-dev-engine -g rg-itg-narrative-dev --tail 50` |
| Restart safely | Any time; live matches resume from their checkpoints |
| Live test | Start the ETL's Stream Analytics job, replay a match, then **stop the job** (it bills while running) |
