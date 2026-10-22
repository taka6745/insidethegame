# Deployment

> **In short:** the nginx image as the public Container App: the viewer, `/viewer-api/` to the internal backend, `/media/hls/` to the feed's internal HLS origin, and `/demo-api/` to demo control, and the developer consoles behind basic auth. Defined in [`terraform/frontend.tf`](../../terraform/frontend.tf) ([runbook](../../terraform/runbook.md)); judges reach it at `https://msft-hackathon.koda-software.com` through the [edge proxy](../../edge-proxy/README.md).

| | |
| --- | --- |
| **Status** | Terraform implemented and planned · applied 22 Oct for the Azure test; acceptance (PLAN.md §10.4) pending · edge proxy deployed 22 Oct |
| **Image** | `frontend/Dockerfile`, pushed to the shared registry as `frontend:<tag>` |
| **Scale** | 0–2 replicas (scales to zero) |
| **URL** | `terraform output public_url` (printed by `./dev azure up`); public name `msft-hackathon.koda-software.com` |

| Setting | Local | Azure |
| --- | --- | --- |
| `BACKEND_UPSTREAM` | `backend:8000` | `itgdemo-backend.internal.<domain>` |
| `MEDIA_ORIGIN`, `FEED_ADMIN_UPSTREAM` | `feed:8000` | `itg-feed-dev-app.internal.<domain>` |
| `DEMO_CONTROL_UPSTREAM` | `demo-control:8000` | `itgdemo-demo.internal.<domain>` |
| `NGINX_RESOLVER` | `127.0.0.11` | `auto` (from `/etc/resolv.conf`) |
| `ENABLE_DEV_ADMIN` | `1` | `1` with `dev_admin` (default), else `0` |
| `DEV_ADMIN_PASSWORD` | unset (no auth) | Container App secret; user `dev` |
| `ETL_ADMIN_UPSTREAM`, `ENGINE_ADMIN_UPSTREAM` | `etl-stream:8000`, `narrative-live:8000` | `itg-etl-dev-admin.internal.<domain>`, `itg-narrative-dev-engine.internal.<domain>` |
| `ETL_ADMIN_TOKEN`, `ENGINE_ADMIN_TOKEN` | unset | Container App secrets; nginx sends `Authorization: Bearer …` on that owner's purge |

With a password, `/dev/`, `/dev-api/`, `/api/`, `/feed-api/` and `/purge-api/*` need basic auth ([`tools/nginx-setup.envsh`](../tools/nginx-setup.envsh)). In Azure `/purge-api/etl` and `/purge-api/engine` reach the owners' internal purge APIs with their bearer tokens, so the `/dev/` purge-all covers every owner; the browser never holds a token. `node tools/test-proxy.ts` checks the rendered config for both modes.

## Public demo API

*In short: four routes, no login, rate-limited.*

| Route | Methods | Limit (over it: `429`) |
| --- | --- | --- |
| `/demo-api/start`, `/demo-api/cancel` | POST only | One shared limit for every viewer: 10/min, burst 5 |
| `/demo-api/state`, `/demo-api/status` | GET only | Per client (`X-Forwarded-For`): 5/s, burst 20 |

nginx strips `Authorization` and proxies to demo control (`DEMO_CONTROL_UPSTREAM`, internal ingress, scales to zero; a `status` call wakes it). Without a reachable demo control `/demo-api/` returns `502` and the viewer hides Start demo. Contract: [local/contracts.md §7a](../../local/contracts.md#7a-demo-control-public).

## Edge proxy

*In short: a custom hostname in front of the Container App.*

A Cloudflare Worker ([`edge-proxy/`](../../edge-proxy/README.md)) forwards every request at `msft-hackathon.koda-software.com` to the frontend's Azure FQDN (`UPSTREAM` in `wrangler.toml`; update it when a redeploy changes the FQDN). It adds no logic; nginx still does all routing and limits.
