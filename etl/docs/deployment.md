# Deployment

> **In short:** Terraform in `infra/` creates the whole pipeline; `devtools azure-setup` then applies the schema and grants the managed identities database access. The Stream Analytics job is created stopped and only bills while running, so a live test is start, replay, verify, stop.

| | |
| --- | --- |
| **Applied by** | `./dev azure up` ([deployment](../../terraform/docs/deployment.md)): the whole pipeline with the multi-match outputs, `match-progress` input, purge API, SPADL app, `sql/azure` triggers and the stream schedule |
| **Demo seeds** | `demo_seeds` sets `DEMO_SEEDS=1` on the admin app; Terraform default off, `./dev azure up` turns it on, `--release` leaves it off |
| **Terraform** | [`infra/`](../infra/), local state (`./dev azure` keeps it in `.local/terraform/etl/`); also hosts the shared Container Apps environment and registry |
| **Region** | Australia East |
| **Cost when idle** | Low: SQL auto-pauses (free offer), DAB scales to zero, the job runs only while match events flow (stream schedule); Event Hubs and Service Bus Standard bill hourly |

## 1. Infrastructure

*In short: one file per concern.*

| File | Creates |
| --- | --- |
| `main.tf` | Resource group, budget alert, naming |
| `messaging.tf` | Event Hubs namespace, hub and consumer groups (`stream-analytics`, `stream-analytics-progress`, `user-backend`); Service Bus namespace, topic `match-notifications`, subscription `narrative-engine`; scoped keys |
| `sql.tf` | SQL server (Entra-only auth, you as admin), firewall rules, serverless database on the free offer |
| `stream_analytics.tf` | The job (query rendered with `window_seconds`, `watermark_idle_seconds`), inputs `match-events` and `match-progress`, nine SQL outputs and the Service Bus output, UDFs |
| `dab.tf` | Log Analytics workspace, Container Apps environment, the DAB app |
| `admin.tf` | Registry; the purge API (`etl-stream` image, `ETL_ROLE=admin`) once `admin_image_tag` is set; its bearer token |
| `stream_schedule.tf` | Metric alerts on `match-events`: incoming messages → start the job; `stream_idle_window` (30 min) quiet → stop it; actions are `terraform/guard` webhooks |
| `spadl.tf` | The SPADL post-processor (`etl-stream` image, `ETL_ROLE=spadl`, 1 replica, no ingress) with the same image tag; `devtools azure-setup` grants its database user |
| `variables.tf`, `outputs.tf`, `versions.tf` | Inputs, outputs (secrets marked sensitive), providers |

## 2. Deploying

*In short: `./dev azure up` applies this stack with the others; `./dev azure plan` previews it.*

`./dev azure up` (confirm with the developer first; it asks before applying) applies `infra/` with its state in `.local/terraform/etl/`, builds and pushes the `etl-stream` image on the host, runs `devtools azure-setup` (migrations, `sql/azure` triggers, identity grants) and starts the job ([terraform deployment](../../terraform/docs/deployment.md)). There is no single-stack command: change `infra/` and rerun `./dev azure up`; unchanged stacks stay as they are. Do not run `terraform` in `infra/` directly: its state there would duplicate every resource.

Purge: the purge API has internal ingress. The `/dev/` Matches panel calls it through the frontend's `/purge-api/etl`, which adds `Authorization: Bearer <admin_token>`; the browser never sees the token. Body: `{"match_id": …}` or `{"all": true}`.

`up` stops the job before applying (query, input and output changes need it stopped), runs `azure-setup` after the apply (DAB and the job's outputs need every migration's tables) and restarts the DAB revision. `azure-setup` also grants DAB `EXECUTE` on `statsAtSeq` and the trend procedures, applies `sql/azure/` (rerunnable) and, once the purge API exists, grants it read and write.

## 3. Running a live replay

*In short: start, replay, check, stop (host Python and `az login`; `devtools` reads the stack's outputs from `.local/terraform/etl/`).*

```sh
.venv/bin/python -m devtools asa start
ETL_EVENTHUB_CONNECTION_STRING=$(.venv/bin/python -m devtools output eventhub_send_connection_string) \
  .venv/bin/python -m seeder.replay seeder/matches/itg-syn-0001.jsonl --speed 10 --target eventhub --match-id demo1
# DAB has internal ingress: expose it only while verifying, then set it back to internal
az containerapp ingress update -g "$(.venv/bin/python -m devtools output resource_group)" -n "$(.venv/bin/python -m devtools output dab_app_name)" --type external
.venv/bin/python -m devtools verify .local/replays/demo1.jsonl --graphql "$(.venv/bin/python -m devtools output graphql_url | sed 's/.internal//')"
az containerapp ingress update -g "$(.venv/bin/python -m devtools output resource_group)" -n "$(.venv/bin/python -m devtools output dab_app_name)" --type internal
.venv/bin/python -m devtools check-notifications .local/replays/demo1.jsonl
.venv/bin/python -m devtools asa stop
```

At ⅓ streaming unit the job runs about two minutes behind a 10x replay. `./dev azure up` sets `window_seconds = 60` for real-time matches (about 40 % SU, about 25 s watermark delay); change it only with the job stopped.

## 4. Access for other services

*In short: Terraform outputs; secrets never printed.*

| Output | For |
| --- | --- |
| `graphql_url` | Narrative engine, user backend (internal address) |
| `servicebus_listen_connection_string` (sensitive) | Narrative engine (`narrative-engine` subscription) |
| `eventhub_send_connection_string` (sensitive) | Seeder or data generation |
| `admin_host`, `admin_token` (sensitive) | Frontend `/purge-api/etl` (the `/dev/` purge on Azure); demo control (purge, seed restore) |
| Event Hubs consumer group `user-backend` | User backend's live event feed |

## 5. Operating

*In short: what to check when something looks wrong.*

| Symptom | Check |
| --- | --- |
| No notifications | Is the job running (`asa status`)? The schedule starts it a minute or two after events arrive. Is a replay sending? Did the guard's last resort stop it (`./dev azure up` restores)? |
| First query slow | DAB scaled to zero or SQL paused; wait about 30 s |
| Missing rows | Run `verify`; output errors are dropped, not retried |
| Subscription backlog | Unread notifications expire after one day (topic TTL) |
