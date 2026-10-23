# Architecture

> **In short:** the browser reaches only the frontend; everything else has internal ingress in one shared Container Apps environment.

| | |
| --- | --- |
| **Environment** | One Container Apps environment and registry, owned by `etl/infra` |
| **Secrets** | Key Vault (backend, via its user-assigned identity) and Container App secrets |
| **Cross-stack** | `terraform_remote_state` from local state; `./dev azure` passes the paths |

## 1. Request and data paths

*In short: viewer traffic through nginx; match data through the ETL.*

```text
browser ─▶ edge proxy (Cloudflare) ─▶ frontend (nginx, public) ─┬▶ /viewer-api → backend ─▶ Postgres, Key Vault, Foundry
                                                                ├▶ /demo-api   → demo control ─▶ feed, ETL, engine, backend; seeds share
                                                                └▶ /media/hls  → feed (its own RG) ─▶ Blob Storage
feed ─▶ Event Hubs ─▶ Stream Analytics ─▶ Azure SQL ─▶ DAB ─▶ backend, engine
                       └▶ Service Bus ─▶ engine (Foundry, Cosmos) ─▶ narratives ─▶ backend
```

## 2. This folder

*In short: the app stack, one file per concern.*

| File | Resources |
| --- | --- |
| `backend.tf` | User backend Container App (one replica, internal) |
| `demo_control.tf` | Demo control (min 1 replica, internal), the `seeds` Azure Files share (demo build) |
| `frontend.tf` | Frontend (nginx, public, scales to zero); `/dev/` basic auth |
| `databases.tf` | Backend PostgreSQL Flexible (`accounts`, `matchapp`) |
| `keyvault.tf` | Key Vault and the backend's secrets |
| `foundry.tf` | The `questions` deployment on the engine's Foundry account |
| `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` | Provider, remote state, inputs, outputs |
