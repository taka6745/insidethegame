# Decisions

> **In short:** why the Azure stack looks as it does (a Free Trial subscription and a hackathon demo shaped it), and what a production release still needs.

| | |
| --- | --- |
| **Demo build** | `demo_seeds` on (seed export/restore routes, Azure Files seeds); public `/demo-api/` without login, rate-limited |
| **Release build** | `./dev azure up --release`: no seed routes; demo control still starts kickoff demos |

## 1. Choices

*In short: trial limits and the demo set most of these.*

| Choice | Why |
| --- | --- |
| One Container Apps environment and registry, owned by `etl/infra`, shared by every app | Free Trial allows one environment per region |
| Images built on the host | No ACR Tasks on the trial |
| Keys in Key Vault and Container App secrets; Key Vault access policies | The account cannot create role assignments |
| Stacks read each other's outputs from local state | One developer deploys; internal addresses are predictable (`<app>.internal.<environment domain>`), so no stack waits for another's app |
| Budgets email only; one last resort at 90 % of the credit | A daily cap must never stop the live demo ([guard](components/guard.md)) |
| Demo control min 1 replica, 1 vCPU / 2 GiB | A cold picker took about 40 s; seeds held in memory make a seeded 60′ start about 8 s |
| Main fixture at full quality, the others re-encoded at about 1.75 Mbit/s | Upload time (about 45 min → 8–10 min per secondary match) |
| User backend and frontend Terraform stay in root `terraform/` | Moving them needs state migration |

## 2. Before a production release

*In short: production gaps and the LATER notes from the infra code.*

| Gap | Required change / evidence |
| --- | --- |
| Demo-only surface | The demo build mounts seed export/restore (`DEMO_SEEDS`) and a public, unauthenticated `/demo-api/` whose Cancel stops the demo for every viewer; a release uses `--release` and puts start/cancel behind auth |
| Spend | A paid subscription needs its own budgets |
| Network | PostgreSQL and SQL public endpoints are limited to Azure services because the shared environment has no VNet; add a VNet environment, private endpoints and DNS (closes the environment's internal plain HTTP too) |
| Identity | Move to managed identities with RBAC and disable local auth: registries (`etl/infra/admin.tf`, `narrative-engine/infra/app.tf`: AcrPull, `admin_enabled = false`); Foundry ("Cognitive Services OpenAI User", `local_auth_enabled = false`); Event Hubs and Service Bus authorization rules (`etl/infra/messaging.tf`, `narrative-engine/infra/messaging.tf`: Entra data roles); Stream Analytics inputs/outputs (`authentication_mode = "Msi"` with Event Hubs Data Receiver and Service Bus Data Sender); the ETL seeder's connection-string path (`etl/seeder/replay.py`) |
| Database logins | ETL apps use least-privilege Azure SQL users (`devtools azure-setup`). The backend (`itgadmin`) and the feed (`feedadmin`) still connect as their PostgreSQL server admins: those servers accept only Azure-service traffic, so `up` cannot reach them to create roles. Add a per-database owner role (no CREATEROLE/CREATEDB) from a one-off job inside the environment, or after the VNet change |
| Exposure | Only the frontend is public; the ETL and engine purges need bearer tokens, which nginx adds behind the `/dev/` basic auth |
| State | Move local state to a protected remote backend for a team |
| Agents | Authentication, per-account quotas and bounded model concurrency for questions |
| Multiple replicas | Fenced match ownership, shared session takeover and durable delivery before more than one backend or feed replica |

Emulators and mock plans don't prove cloud identity, networking, durability or capacity. Load-test fan-out, reconnect bursts and model throughput separately ([scaling](../../user-backend/docs/architecture.md#6-scaling-boundary)).
