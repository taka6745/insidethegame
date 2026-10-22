# Deploy everything to Azure

> **In short:** `./dev azure up` builds the whole stack from an empty subscription and prints the public URL; `./dev azure down` removes it all and confirms nothing billable is left. **Applied 22 Oct** for the Azure test; the demo acceptance (PLAN.md §10.4) is pending. The judge URL `msft-hackathon.koda-software.com` is a Cloudflare Worker in front of it ([§3a](#3a-judge-url-edge-proxy)).

| | |
| --- | --- |
| **Status** | Applied 22 Oct (guard, ETL, engine, feed, app incl. demo control and seeds share); acceptance pending. `gpt-6.1-sol` deployments are in Terraform and roll out on the next `up` |
| **Models** | Foundry `gpt-6.1-sol` GlobalStandard: `writer` (engine, 200K TPM), `questions` (backend, 50K TPM), effort low · `Microsoft-Decision-1` DataZoneStandard 50 RPM (engine) |
| **Build** | Judge build by default (`demo_seeds` on); `--release` turns the seed routes off |
| **Needs** | Docker, `az login` (Owner: the spend guard assigns its own role), host `ffmpeg` (secondary video), about 5.5 GB upload for the match video |
| **State** | `.local/terraform/<stack>/terraform.tfstate` (git-ignored, local only) |
| **Region** | Australia East |
| **Cost** | About US$10/day while up ([§5](#5-cost)); nothing after `down` |

## 1. Commands

*In short: four commands; up and down ask first unless `--yes`.*

```sh
./dev azure plan      # plan every stack; stacks not applied yet are stood in for by placeholder outputs
./dev azure up        # deploy, seed, start; prints the viewer URL (--release: no demo seed routes)
./dev azure status    # resources, running state, estimated monthly cost
./dev azure down      # destroy in reverse, purge soft-deleted resources, check 0 remain
```

Terraform, the Azure CLI and sqlcmd run in the toolbox image ([`azure/Dockerfile`](azure/Dockerfile), the same pinned Terraform as `./dev terraform check`) with your `~/.azure` mounted. Images are built on the host for `linux/amd64`. Secrets stay in state and Key Vault; nothing prints them.

## 2. What `up` does, in order

*In short: ETL first, then the engine, the provider, our app.*

```text
0 terraform/guard       apply (budgets, last resort, Stream Analytics schedule; kept by down)
1 etl/infra             apply (window_seconds = 60: the feed plays in real time; the guard's schedule alerts) → devtools azure-setup (migrations, triggers)
2 images                build + push etl-stream, feed, user-backend, demo-control, frontend → ETL registry (shared)
3 etl/infra             apply with admin_image_tag → devtools azure-setup (grants for the new apps) → restart DAB
4 narrative-engine/infra apply → push narrative-engine → apply with engine_image_tag, user_backend_url
5 data-generation/infra apply → upload recordings + match video (azcopy; secondary fixtures re-encoded) → apply with image_tag
6 terraform/            apply with image_tag (backend, demo control, frontend, Postgres, Key Vault, Foundry deployment)
7 Stream Analytics      start (bills while running)
```

| Stack | Resource group | Owns |
| --- | --- | --- |
| [`etl/infra`](../etl/infra/) | `rg-itg-etl-dev` | Event Hubs, Stream Analytics, Azure SQL (free offer), DAB, purge API, Service Bus, **the shared Container Apps environment and registry** |
| [`narrative-engine/infra`](../narrative-engine/infra/) | `rg-itg-narrative-dev` | Azure AI Foundry (Azure OpenAI `gpt-6.1-sol` as deployment `writer`, Microsoft-Decision-1), Cosmos DB, engine app, topic `narratives`, Application Insights |
| [`data-generation/infra`](../data-generation/infra/) | `rg-itg-feed-dev` | The simulated provider: feed app, its own PostgreSQL and Blob Storage |
| [`terraform/`](.) | `itgdemo-rg` | User backend, demo control (`/demo-api/`, one replica, scales to zero), the `seeds` Azure Files share (judge build), frontend, backend PostgreSQL, Key Vault, the question agents' Foundry deployment (`questions`) |
| [`terraform/guard`](guard/) | `rg-itg-guard` | Budgets, the last resort and the Stream Analytics schedule ([§4](#4-spend-guard-and-idle-saver)); kept by `down` |

Match video: [`azure/media.json`](azure/media.json) names the main fixture, uploaded at full quality (Redcastle Town–Port Albion, about 3.3 GB); the others are re-encoded once by [`azure/encode_media.sh`](azure/encode_media.sh) (720p25 H.264 about 1.75 Mbit/s, same segment names, timestamps and keyframes; about 1.1 GB each) into `.local/grf-demo-<fixture>-90-low/`. `azcopy sync` uploads many files in parallel and skips unchanged ones; the playlist goes last; `up` checks the segment count. `--release` turns off the demo seed routes (`demo_seeds`, on for the judge build; seeds sit on an Azure Files share mounted into demo control).

Stacks read each other's outputs from local state (`terraform_remote_state`); `./dev azure` passes the paths. Internal addresses are predictable (`<app>.internal.<environment domain>`), so no stack waits for another's app.

Rerun `up` after a failure: it keeps the apps on the last complete up's image tag (`.local/terraform/image-tag.txt`) until new images are pushed, `azure-setup` recreates the container apps' database users for their current identities, and starting an already running Stream Analytics job is a no-op. The SPADL post-processor starts before its database user is granted (step 3); it logs `SPADL step failed; retrying` until then, and the backend's and engine's SPADL reads wait for `spadlSeq`.

## 3. After `up`

*In short: press Start demo at `<url>/`, or start a match from /dev/.*

- The viewer's **Start demo** calls demo control (`/demo-api/`, internal app, one replica, scales to zero): three matches, main game first; seeded start points need seeds on the `seeds` Azure Files share (recorded with the winning model: `demo_control.py record`/`capture` run inside demo control with `az containerapp exec`; 20′, HT, 60′ and 85′ recorded on sol 23 Oct, PLAN.md §11).
- Open `<url>/dev/` (user `dev`, password in `.local/terraform/dev-admin-password.txt`) → Matches → start. Matches start at the next whole minute, from 00:00.
- The viewer is `<url>/`. Questions, replays and the follow planner use Azure OpenAI `gpt-6.1-sol` (deployment `questions`, effort low) on the engine's Foundry account; narratives use the engine's deployments, and story follows and claim checks its Microsoft-Decision-1 deployment.
- The `/dev/` panel's purge reaches every owner: the feed and backend directly, the ETL purge API and the engine through `/purge-api/{etl,engine}`, where nginx adds each owner's bearer token (Container Apps secrets). Only the frontend is public; DAB, engine, purge API, feed and backend have internal ingress.
- Stop Stream Analytics between demos (`cd etl && python -m devtools asa stop` with that state, or just `./dev azure down`).

## 3a. Judge URL (edge proxy)

*In short: [`edge-proxy/`](../edge-proxy/README.md) is a Cloudflare Worker that proxies `msft-hackathon.koda-software.com` to the frontend. Deployed 22 Oct.*

```sh
cd edge-proxy && npx wrangler@4.151.3 deploy   # Cloudflare creates the DNS record and certificate
```

`UPSTREAM` in `wrangler.toml` is the frontend's Container Apps FQDN; after a `down`/`up` changes it, update it and deploy again. The Worker is outside Azure and outside `./dev azure down`.

## 4. Spend guard and idle saver

*In short: budgets only email; Stream Analytics runs only while matches play; one last resort near the end of the credit keeps the viewer serving. Applied first by `up`, kept by `down`.*

[`guard/`](guard/) (resource group `rg-itg-guard`, its own state `.local/terraform/guard`, tag `insidethegame-guard`):

| Piece | What it does |
| --- | --- |
| `budget-insidethegame` | A$15/day as a A$450 monthly budget (no daily grain in Azure). Emails at actual 50/80/100 % and forecast 100 %. **Never stops anything**: judging must not be interrupted |
| `budget-insidethegame-credit` | The trial credit (A$285 from 1 Oct: A$4.6 spent + about A$281 left on 22 Oct). Emails at actual 50/75 % and forecast 100 %; at **actual 90 %** (about A$28, several idle days, left) the last resort runs |
| Last resort | Stops Stream Analytics, the feed and the SPADL post-processor and the feed's PostgreSQL. Frontend, backend, DAB, engine and their stores keep running, so the viewer and finished matches' replays still work; new matches can't start. Forecasts don't trigger it: a forecast runs to the period's end, past judging, and would stop the demo too early |
| Stream Analytics schedule | `etl/infra/stream_schedule.tf`: an Event Hubs alert (match events in the last minute) starts the job, resuming after its last output so buffered events are processed; 30 minutes without match events (longer than half time) stops it. Kick-off is processed a few minutes late, then catches up |
| Runbook | `guard.ps1` in an Automation account (East US: Free Trial can't create one in Australia East), modes `stream-start`, `stream-stop`, `last-resort`, one webhook each. Its identity has a custom role: read, start and stop only; it never writes or deletes |

`./dev azure up` restores anything the runbook stopped. Azure's own spending limit (On for Free Trial) is the hard stop at zero credit.

## 5. Cost

*In short: about US$300/month if left up; tear down between demos.*

| Item | ~US$/month while up |
| --- | --- |
| Container Apps: backend, feed, engine (0.5 vCPU, always on) | 115 (39 each, less the free grant) |
| Container Apps: frontend, DAB, purge API (scale to zero) | ~1 |
| Stream Analytics (⅓ streaming unit, while running) | 85 |
| PostgreSQL Flexible B1ms × 2 (backend, feed) | 38 |
| Event Hubs Standard + Service Bus Standard | 35 |
| Registries (Basic × 2), Log Analytics, Storage (~10 GB), Cosmos DB serverless, Key Vault | 20 |
| Azure SQL (free offer) | 0 |
| **Total** | **≈ 295 (≈ US$10/day)** |

Usage on top: model tokens (cents per match), internet egress beyond 100 GB/month (each viewer streams about 2 GB per hour of video, about US$0.12/GB). `./dev azure status` estimates the current state.

## 6. Before the first `up`

*In short: check quota, then go.*

- Foundry quota in Australia East: GlobalStandard `gpt-6.1-sol` (250K TPM: `writer` 120K, `questions` 130K), DataZoneStandard `Microsoft-Decision-1` (50 requests/minute).
- Resource providers registered once: `Microsoft.App`, `Microsoft.ContainerRegistry`, `Microsoft.CognitiveServices`, `Microsoft.DBforPostgreSQL`, `Microsoft.DocumentDB`, `Microsoft.EventHub`, `Microsoft.ServiceBus`, `Microsoft.Sql`, `Microsoft.StreamAnalytics`, `Microsoft.KeyVault`, `Microsoft.Storage`, `Microsoft.Insights`, `Microsoft.OperationalInsights`, `Microsoft.ManagedIdentity`.
- Trial limits shape the design: one Container Apps environment per region (all apps share the ETL's), no ACR Tasks (images build locally), no role assignments (keys in Key Vault and Container App secrets; Key Vault uses access policies).
- Budget alerts (ETL, engine) go to the signed-in account's email.

## 7. `down`

*In short: reverse destroy, then a safety net.*

Stream Analytics jobs in our groups are stopped first (even without state); `terraform destroy` for app → feed → narrative → etl (a failed destroy does not stop the sweep); any of our resource groups still present are deleted, dependants first, and only if they carry our `project` tag; soft-deleted Foundry accounts and Key Vaults from our resource groups are purged (deleted Cosmos DB accounts sit in a free restore window and block nothing: names carry a random suffix per deploy). It fails unless no resource group or `project`-tagged resource remains. The spend guard (`rg-itg-guard`, tag `insidethegame-guard`) stays: it costs nothing idle and protects the next `up`; remove it with `terraform destroy` in `terraform/guard` against `.local/terraform/guard` state if wanted.
