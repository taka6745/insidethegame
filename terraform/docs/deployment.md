# Deployment

> **In short:** `./dev azure up` builds the whole stack from an empty subscription and prints the public URL; `./dev azure down` removes it and confirms nothing billable is left. The demo URL `msft-hackathon.koda-software.com` is a Cloudflare Worker in front of it ([§4](#4-demo-url-edge-proxy)).

| | |
| --- | --- |
| **Models** | Foundry GlobalStandard: `writer` (`gpt-6.1-sol`, engine, 120K TPM), `questions` (`gpt-6.1-sol`, backend, 130K TPM), effort low; alternates `gpt-6-luna` and `gpt-5-mini` (100K TPM each), selectable per role in `/dev/` → Models · `Microsoft-Decision-1` DataZoneStandard 50 RPM |
| **Build** | Demo build by default (`demo_seeds` and `demo_control` on); `--release` turns the seed routes, demo control and the viewer's public `/demo-api/` off |
| **Needs** | Docker, `az login` (Owner: the spend guard assigns its own role), host `ffmpeg` (secondary video), about 5.5 GB upload for the match video |
| **State** | `.local/terraform/<stack>/terraform.tfstate` (git-ignored, local only) |
| **Region** | Australia East (the guard's Automation account: East US) |
| **Cost** | About A$7–8/day idle with demo control kept warm ([§6](#6-cost)); nothing after `down` except the guard |

## 1. Commands

*In short: four commands; up and down ask first unless `--yes`.*

```sh
./dev azure plan      # plan every stack; stacks not applied yet are stood in for by placeholder outputs
./dev azure up        # deploy, seed, start; prints the viewer URL (--release: no demo seed routes)
./dev azure status    # resources, running state, estimated monthly cost
./dev azure down      # destroy in reverse, purge soft-deleted resources, check 0 remain
```

Terraform, the Azure CLI and sqlcmd run in the toolbox image ([components/azure](components/azure.md)) with your `~/.azure` mounted. Images are built on the host for `linux/amd64`. Secrets stay in state and Key Vault; nothing prints them. Confirm with the developer before any apply.

## 2. What `up` does, in order

*In short: guard, ETL, the engine, the provider, our app, then Stream Analytics.*

```text
0 terraform/guard        apply (budgets, last resort, hard stop, Stream Analytics schedule; kept by down)
1 etl/infra              apply → devtools azure-setup (migrations, triggers)
2 images                 build + push etl-stream, feed, user-backend, demo-control, frontend → ETL registry (shared)
3 etl/infra              apply with admin_image_tag → azure-setup (grants for the new apps) → restart DAB
4 narrative-engine/infra apply → push narrative-engine → apply with engine_image_tag, user_backend_url
5 data-generation/infra  apply → upload recordings + match video (azcopy) → apply with image_tag
6 terraform/             apply with image_tag (backend, demo control, frontend, Postgres, Key Vault, questions)
7 Stream Analytics       start (bills while running)
```

Rerun `up` after a failure: apps keep the last complete up's image tag (`.local/terraform/image-tag.txt`) until new images are pushed, `azure-setup` recreates the database users for the apps' current identities, and starting a running Stream Analytics job is a no-op. The SPADL post-processor starts before its database user is granted (step 3) and logs `SPADL step failed; retrying` until then.

## 3. After `up`

*In short: press Start demo at `<url>/`, or start a match from `/dev/`.*

- **Start demo** calls demo control (`/demo-api/`, internal, one replica kept warm). Seeded start points need seeds on the `seeds` share: run `demo_control.py record`/`capture` inside demo control with `az containerapp exec` ([demo control](../../local/docs/components/demo-control.md)).
- `<url>/dev/` (user `dev`, password in `.local/terraform/dev-admin-password.txt`) → Matches → start. Matches start at the next whole minute, from 00:00.
- The `/dev/` purge reaches every owner: the feed via `/feed-api/`, ETL, engine and backend via `/purge-api/{owner}` (nginx adds the ETL and engine bearer tokens).
- Stream Analytics starts and stops itself with match traffic ([guard](components/guard.md)); `cd etl && python3 -m devtools asa stop` stops it by hand (host Python and `az login`; it reads `.local/terraform/etl/`).

## 4. Demo URL (edge proxy)

*In short: [`edge-proxy/`](../../edge-proxy/README.md) proxies `msft-hackathon.koda-software.com` to the frontend.*

```sh
cd edge-proxy && npx wrangler@4.151.3 deploy   # Cloudflare creates the DNS record and certificate
```

`UPSTREAM` in `wrangler.toml` is the frontend's Container Apps FQDN; after a `down`/`up` changes it, update it and deploy again. The Worker is outside Azure and outside `./dev azure down`.

## 5. Before the first `up`

*In short: check quota and providers, then go.*

- Foundry quota in Australia East: GlobalStandard `gpt-6.1-sol` 250K TPM (`writer` 120K + `questions` 130K), `gpt-6-luna` and `gpt-5-mini` 100K each; DataZoneStandard `Microsoft-Decision-1` 50 requests/minute.
- Resource providers registered once: `Microsoft.App`, `Microsoft.ContainerRegistry`, `Microsoft.CognitiveServices`, `Microsoft.DBforPostgreSQL`, `Microsoft.DocumentDB`, `Microsoft.EventHub`, `Microsoft.ServiceBus`, `Microsoft.Sql`, `Microsoft.StreamAnalytics`, `Microsoft.KeyVault`, `Microsoft.Storage`, `Microsoft.Insights`, `Microsoft.OperationalInsights`, `Microsoft.ManagedIdentity`.
- Budget alerts go to the signed-in account's email.

## 6. Cost

*In short: idle costs a few dollars a day; each demo session adds model tokens.*

| Item | Estimate |
| --- | --- |
| Idle, Stream Analytics stopped, SQL paused | About A$6–7/day: container apps at the idle rate 2.1, PostgreSQL B1ms × 2 1.9, Event Hubs 1.1, Service Bus 0.5, registries 0.5 |
| Demo control kept warm (min 1 replica) | About A$0.6–1.2/day |
| One session, three matches to half time on `gpt-6.1-sol` | About US$2 (A$3) of tokens |
| Stream Analytics (⅓ streaming unit) | Only while match events flow |

Egress beyond 100 GB/month costs about US$0.12/GB (a viewer streams about 2 GB per hour of video). `./dev azure status` estimates the current state.

## 7. `down`

*In short: reverse destroy, then a safety net.*

Stream Analytics jobs in our groups stop first; `terraform destroy` runs for app → feed → narrative → etl (a failed destroy does not stop the sweep); any of our resource groups still present are deleted, dependants first, only if they carry our `project` tag; soft-deleted Foundry accounts and Key Vaults are purged; resource-group budgets are deleted. It fails unless no resource group or `project`-tagged resource remains. The spend guard (`rg-itg-guard`) stays: it costs nothing idle and protects the next `up`.
