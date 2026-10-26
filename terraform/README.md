# Azure infrastructure

The whole stack in Terraform: five stacks that `./dev azure up` applies in order from an empty subscription and `./dev azure down` removes, keeping the spend guard. Daily development uses [Docker Compose](../local/README.md); Azure is for the deployed demo.

```text
browser ─▶ edge proxy (Cloudflare) ─▶ frontend (nginx, public) ─┬▶ /viewer-api → backend ─▶ Postgres, Key Vault, Foundry
                                                                ├▶ /demo-api   → demo control ─▶ feed, ETL, engine, backend; seeds share
                                                                └▶ /media/hls  → feed (its own RG) ─▶ Blob Storage
feed ─▶ Event Hubs ─▶ Stream Analytics ─▶ Azure SQL ─▶ DAB ─▶ backend, engine
                       └▶ Service Bus ─▶ engine (Foundry, Cosmos) ─▶ narratives ─▶ backend
```

| Order | Stack | Resource group | Owns |
| --- | --- | --- | --- |
| 0 | [`guard/`](guard/) | `rg-itg-guard` (kept by `down`) | Budgets, Stream Analytics start/stop runbook, last resort, hard stop |
| 1 | [`etl/infra/`](../etl/infra/) | `rg-itg-etl-dev` | Event Hubs, Stream Analytics and its schedule, Azure SQL, DAB, purge API, SPADL app, Service Bus `match-notifications`, the shared Container Apps environment and registry |
| 2 | [`narrative-engine/infra/`](../narrative-engine/infra/) | `rg-itg-narrative-dev` | Azure AI Foundry (`writer`, `gpt-6-luna`, `gpt-5-mini`, `decision-1`), Cosmos DB, engine app, Service Bus `narratives`, Application Insights |
| 3 | [`data-generation/infra/`](../data-generation/infra/) | `rg-itg-feed-dev` | The simulated provider: PostgreSQL, Blob Storage, feed app |
| 4 | `terraform/` (this folder) | `itgdemo-rg` | User backend, demo control, frontend, seeds share, backend PostgreSQL, Key Vault, the `questions` Foundry deployment |

The browser reaches only the frontend; everything else has internal ingress in one shared Container Apps environment. Stacks read each other's outputs from local state (`.local/terraform/<stack>/`); `./dev azure` passes the paths. Region Australia East (the guard's Automation account: East US). Status: deployed, demo build ([root README](../README.md#status)).

## Commands

| Command | Does |
| --- | --- |
| `./dev terraform check` | `fmt`, `validate` and mock-provider tests for all five stacks in Docker; no Azure calls (also CI) |
| `cd terraform/azure && python3 -m unittest test_azure -v` | `./dev azure` against a faked toolbox (also CI) |
| `./dev azure plan` | Real plan against your subscription (`az login`); applies nothing |
| `./dev azure up [--release] [--yes]` | Deploy, seed, start; prints the viewer URL. `--release`: no demo seed routes, no demo control, `/demo-api/` is `404` |
| `./dev azure status` | Resources, running state, estimated monthly cost |
| `./dev azure guard` | Apply the spend guard alone |
| `./dev azure down` | Destroy app → feed → narrative → etl, sweep `project`-tagged leftovers, purge soft-deleted Foundry and Key Vault; fails unless nothing billable remains; the guard stays |
| `cd edge-proxy && npx wrangler@4.151.3 deploy` | Redeploy the Cloudflare Worker after `up` rewrote its `UPSTREAM` |

Needs Docker, `az login` (Owner: the guard assigns its own role), host `ffmpeg` (secondary video), about 5.5 GB upload for the match video. Terraform 1.13.4, the Azure CLI, go-sqlcmd and azcopy run in a pinned toolbox image (`azure/Dockerfile`) with your `~/.azure` mounted; secrets go from state into `TF_VAR_*`, never printed. Confirm with the developer before any apply; never commit state or tfvars; `up` and `down` ask first unless `--yes`.

What `up` does, in order: guard apply · `etl/infra` apply → `devtools azure-setup` (migrations, triggers) · build and push `etl-stream`, `feed`, `user-backend`, `demo-control`, `frontend` images (host, `linux/amd64`) · `etl/infra` apply with the image tag → `azure-setup` grants → restart DAB · `narrative-engine/infra` apply → push engine → apply with tag and backend URL · `data-generation/infra` apply → upload recordings and video (`azcopy`; `azure/media.json` keeps the main game at full quality, `encode_media.sh` re-encodes the others to about 1.75 Mbit/s) → apply with tag · `terraform/` apply · start Stream Analytics. Rerun after a failure: apps keep the last complete image tag, `azure-setup` recreates database users, starting a running job is a no-op.

After `up`: press **Start demo** at `<url>/`, or `<url>/dev/` (user `dev`, password in `.local/terraform/dev-admin-password.txt`) → Matches → start. Seeded starts need seeds on the `seeds` share ([demo control](../local/README.md#demo-control)). Stream Analytics starts and stops itself with match traffic; `cd etl && python3 -m devtools asa stop` stops it by hand. Before the first `up`: Foundry quota in Australia East (`gpt-6.1-sol` GlobalStandard 250K TPM for `writer` 120K + `questions` 130K; `gpt-6-luna`, `gpt-5-mini` 100K each; `Microsoft-Decision-1` DataZoneStandard 50 RPM) and the resource providers (`Microsoft.App`, `ContainerRegistry`, `CognitiveServices`, `DBforPostgreSQL`, `DocumentDB`, `EventHub`, `ServiceBus`, `Sql`, `StreamAnalytics`, `KeyVault`, `Storage`, `Insights`, `OperationalInsights`, `ManagedIdentity`).

## This folder

| File | Resources |
| --- | --- |
| `backend.tf` | User backend Container App (one replica, internal) |
| `demo_control.tf` | Demo control (min 1 replica, internal), the `seeds` Azure Files share (demo build only) |
| `frontend.tf` | Frontend (nginx, public, scales to zero); `/dev/` basic auth |
| `databases.tf` | Backend PostgreSQL Flexible (`accounts`, `matchapp`) |
| `keyvault.tf` | Key Vault and the backend's secrets |
| `foundry.tf` | The `questions` deployment on the engine's Foundry account |
| `azure/` | `azure.py` (`./dev azure`, standard library only), toolbox `Dockerfile`, `media.json`, `encode_media.sh`, `test_azure.py` |
| `tests/design.tftest.hcl`, `guard/tests/guard.tftest.hcl` | Mock-provider tests of the app stack and the guard |

## Spend guard

Budgets only email; Stream Analytics runs only while matches play; one last resort near the end of the credit keeps the viewer serving; the hard stop at the credit itself stops everything. Applied first by `up`, kept by `down`; `rg-itg-guard`, runbook `guard.ps1` in an Automation account (East US; modes `stream-start`, `stream-stop`, `last-resort`, `hard-stop`, one webhook each; a custom role that reads, starts and stops only).

| Piece | Does |
| --- | --- |
| `budget-insidethegame` | A$15/day as a A$450 monthly budget; emails at actual 50/80/100 % and forecast 100 %; never stops anything |
| `budget-insidethegame-credit` | The trial credit (A$285 from 1 Oct, expires 17 Nov); emails at 50/75 % and forecast 100 %; actual 90 % runs the last resort, actual 100 % the hard stop. Forecasts never trigger them (two heavy days read as a month of them) |
| Last resort | Stops Stream Analytics, the feed, the SPADL post-processor and the feed's PostgreSQL; frontend, backend, DAB, engine and stores keep running, so the viewer and replays still work |
| Hard stop | Stops every container app and PostgreSQL server in the four stack groups. Budgets evaluate a few times a day, so up to a day's spend can still land |
| Stream Analytics schedule | `etl/infra/stream_schedule.tf`: an Event Hubs alert (events in the last minute) starts the job, 30 quiet minutes stop it; demo control also calls the stream-start webhook on Start, so only the job's own 75–90 s start remains |

`./dev azure up` restores anything the runbook stopped. Azure's own spending limit (on for Free Trial) is the hard stop at zero credit.

## Cost and deploy record

| Item | Estimate |
| --- | --- |
| Idle, Stream Analytics stopped, SQL paused | About A$6–7/day (container apps 2.1, PostgreSQL B1ms × 2 1.9, Event Hubs 1.1, Service Bus 0.5, registries 0.5) plus demo control kept warm (0.6–1.2) |
| One session, three matches to half time on `gpt-6.1-sol` | About US$2 (A$3) of tokens |
| Stream Analytics (⅓ streaming unit) | Only while match events flow |
| Egress | About US$0.12/GB beyond 100 GB/month (a viewer streams about 2 GB per hour of video) |

Demo build live since 23 Oct 2026 (fictional league, every agent on `gpt-6.1-sol`); last deploy 26 Oct, `7208b2b`, image `v20261026115330` (spend guard hard stop, runbook recreated). Fixed while deploying: Stream Analytics compile and memory limits, the guard's Automation account in East US, serverless SQL resume retries, azcopy media upload, the feed's pooled Postgres connections, concurrent HLS blob purge.

## Decisions and production gaps

| We chose | Because |
| --- | --- |
| One Container Apps environment and registry, owned by `etl/infra` | Free Trial allows one environment per region |
| Images built on the host | No ACR Tasks on the trial |
| Keys in Key Vault and Container App secrets | The account cannot create role assignments |
| Stacks read each other's outputs from local state | One developer deploys; internal addresses are predictable |
| Budgets email only; last resort at 90 %, hard stop at 100 % | A daily cap must never stop the live demo |
| Demo control min 1 replica, 1 vCPU / 2 GiB; seeds held in memory | A cold picker took about 40 s; a seeded 60′ start now takes about 8 s |
| Main fixture at full quality, the others at about 1.75 Mbit/s | Upload time (about 45 min → 8–10 min per secondary match) |
| Hub, topic and subscription names from stack outputs; `up` rewrites the edge proxy's `UPSTREAM` | No hand edits after a redeploy |

| Gap before a production release | Change |
| --- | --- |
| Demo-only surface | `--release` already removes seed routes and demo control; put start/cancel behind auth |
| Network | A VNet environment, private endpoints and DNS (PostgreSQL and SQL are limited to Azure-service traffic today) |
| Identity | Managed identities with RBAC and local auth off: registries (AcrPull), Foundry ("Cognitive Services OpenAI User"), Event Hubs and Service Bus data roles, Stream Analytics `authentication_mode = "Msi"` |
| Database logins | The backend and the feed still connect as their PostgreSQL server admins; add a per-database owner role from a job inside the environment |
| State, spend | A protected remote backend; a paid subscription's own budgets |
| Agents, replicas | Authentication, per-account quotas and bounded model concurrency for questions; fenced match ownership and durable delivery before a second backend or feed replica ([backend](../user-backend/README.md#limits)) |
| Frontend delivery | Static assets behind a CDN; the socket transport replaced by an authenticated gateway or Azure Web PubSub |

Emulators and mock plans don't prove cloud identity, networking, durability or capacity.
