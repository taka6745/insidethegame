# From the local demo to Azure

> **In short:** Terraform for every service; **applied 22 Oct** for the Azure test, demo acceptance (PLAN.md §10.4) pending. `./dev azure up` deploys the spend guard, feed, ETL, narrative engine, user backend, demo control and frontend ([runbook](runbook.md)); the edge proxy serves the judge URL. Below: what a production release still needs.

| | |
| --- | --- |
| **Judge build** | `demo_seeds` on (seed export/restore routes, Azure Files seeds); public `/demo-api/` without login, rate-limited |
| **Release build** | `./dev azure up --release`: no seed routes; demo control still starts kickoff demos |
| **Models** | `gpt-6.1-sol` (`writer`, `questions`) in Terraform, rollout pending; Microsoft-Decision-1 applied |

```text
Local:  feed → Event Hubs (emulator) → etl-stream → SQL Server + DAB ─┬→ narrative-live → Service Bus → backend → viewer
Azure:  feed → Event Hubs → Stream Analytics → Azure SQL + DAB ───────┴→ engine (Foundry, Cosmos) → Service Bus → backend → frontend ← edge proxy
        demo control (/demo-api/) → feed, ETL, engine, backend (purge; seed restore in the judge build)
```

| Before a production release | Required change / evidence |
| --- | --- |
| First Azure run | Applied 22 Oct; still to prove (PLAN.md §10.4): Start demo at every point from a fresh browser, seeds recorded on Azure with `gpt-6.1-sol`, the Stream Analytics query and schedule on live matches, D1–D7 targets, 12 h idle cost |
| Demo-only surface | The judge build mounts seed export/restore (`DEMO_SEEDS`) and a public, unauthenticated `/demo-api/` whose Cancel stops the demo for every viewer; a release uses `--release` and should put start/cancel behind auth |
| Spend | Budgets email only; the guard's last resort (90 % of the credit) stops ingestion but keeps the viewer up. A paid subscription needs its own budgets |
| Network | Public endpoints limited to Azure services (PostgreSQL, SQL) because the shared environment has no VNet; add a VNet environment, private endpoints and DNS |
| Identity | Keys in Key Vault and Container App secrets because the account cannot create role assignments; move to managed identities with RBAC, disable local auth |
| Database logins | ETL apps use least-privilege Azure SQL users (`devtools azure-setup`). The backend (`itgadmin`) and the feed (`feedadmin`) still connect as their PostgreSQL server admins: those servers accept only Azure-service traffic, so `up` cannot reach them to create roles. Add a per-database owner role (no CREATEROLE/CREATEDB; the apps run their own migrations) from a one-off job inside the environment, or after the VNet change |
| Exposure | Only the frontend is public. Engine, DAB, purge API, feed and backend have internal ingress; the ETL and engine purges also need bearer tokens, which nginx adds behind the `/dev/` basic auth. A VNet would also close the environment's internal plain HTTP |
| State | Local state under `.local/terraform/`; move to a protected remote backend for a team |
| Agents | Authentication, per-account quotas and bounded model concurrency for questions |
| Multiple replicas | Fenced match ownership, shared session takeover and durable delivery before more than one backend or feed replica |

Emulators and mock plans don't prove cloud identity, networking, durability or capacity. Load-test fan-out, reconnect bursts and model throughput separately ([scaling](../user-backend/docs/architecture.md#6-scaling-boundary)).
