# Deployment

> **In short:** Terraform in `infra/` creates the whole pipeline; `devtools azure-setup` then applies the schema and grants the managed identities database access. The Stream Analytics job is created stopped and only bills while running, so a live test is start, replay, verify, stop.

| | |
| --- | --- |
| **Status** | Deployed to dev |
| **Terraform** | [`infra/`](../infra/), local state |
| **Region** | Australia East |
| **Cost when idle** | Low: SQL auto-pauses (free offer), DAB scales to zero, the job is stopped; Event Hubs and Service Bus Standard bill hourly |

## 1. Infrastructure

*In short: one file per concern.*

| File | Creates |
| --- | --- |
| `main.tf` | Resource group, budget alert, naming |
| `messaging.tf` | Event Hubs namespace, hub and consumer groups; Service Bus namespace, topic `match-notifications`, subscription `narrative-engine`; scoped keys |
| `sql.tf` | SQL server (Entra-only auth, you as admin), firewall rules, serverless database on the free offer |
| `stream_analytics.tf` | The job (query rendered with `window_seconds`), input, SQL and Service Bus outputs, UDFs |
| `dab.tf` | Log Analytics workspace, Container Apps environment, the DAB app |
| `variables.tf`, `outputs.tf`, `versions.tf` | Inputs, outputs (secrets marked sensitive), providers |

## 2. Deploying

*In short: apply, then set up the database.*

```sh
cd etl
cp infra/local.auto.tfvars.example infra/local.auto.tfvars    # subscription and budget emails
terraform -chdir=infra init
terraform -chdir=infra apply
.venv/Scripts/python -m devtools azure-setup                    # migrations + identity grants
```

Stop the job before an apply that changes its query, inputs or outputs.

## 3. Running a live replay

*In short: start, replay, check, stop.*

```sh
.venv/Scripts/python -m devtools asa start
ETL_EVENTHUB_CONNECTION_STRING=$(terraform -chdir=infra output -raw eventhub_send_connection_string) \
  .venv/Scripts/python -m seeder.replay seeder/matches/itg-syn-0001.jsonl --speed 10 --target eventhub --match-id demo1
.venv/Scripts/python -m devtools verify .local/replays/demo1.jsonl --graphql "$(terraform -chdir=infra output -raw graphql_url)"
.venv/Scripts/python -m devtools check-notifications .local/replays/demo1.jsonl
.venv/Scripts/python -m devtools asa stop
```

At ⅓ streaming unit the job runs about two minutes behind a 10x replay. For a real-time match, set `window_seconds = 60` and apply (with the job stopped).

## 4. Access for other services

*In short: Terraform outputs; secrets never printed.*

| Output | For |
| --- | --- |
| `graphql_url` | Narrative engine, user backend |
| `servicebus_listen_connection_string` (sensitive) | Narrative engine (`narrative-engine` subscription) |
| `eventhub_send_connection_string` (sensitive) | Seeder or data generation |
| Event Hubs consumer group `user-backend` | User backend's live event feed |

## 5. Operating

*In short: what to check when something looks wrong.*

| Symptom | Check |
| --- | --- |
| No notifications | Is the job running (`asa status`)? Is a replay sending? |
| First query slow | DAB scaled to zero or SQL paused; wait about 30 s |
| Missing rows | Run `verify`; output errors are dropped, not retried |
| Subscription backlog | `narrative-engine` has no message TTL; old replays stay until read |
