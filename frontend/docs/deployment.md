# Deployment

> **In short:** the nginx image runs as the public Container App: the viewer, `/viewer-api/` to the internal backend, `/media/hls/` to the feed's internal HLS origin, `/demo-api/` to demo control, and the developer consoles behind basic auth. Defined in [`terraform/frontend.tf`](../../terraform/frontend.tf) ([Terraform deployment](../../terraform/docs/deployment.md)); the public name goes through the [edge proxy](../../edge-proxy/README.md).

| | |
| --- | --- |
| **Image** | `frontend/Dockerfile` (Node build stage, nginx serves only compiled output), pushed to the shared registry as `frontend:<tag>` |
| **Scale** | 0–2 replicas |
| **URL** | Printed by `./dev azure up` (the app stack's output `public_url`); public name `msft-hackathon.koda-software.com` |

## 1. Settings

*In short: upstreams and gates are environment variables rendered into the nginx template at start.*

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

With a password, `/dev/`, `/dev-api/`, `/lab/`, `/api/`, `/feed-api/` and `/purge-api/*` need basic auth ([`tools/nginx-setup.envsh`](../tools/nginx-setup.envsh)); the basic-auth header is never forwarded upstream. In Azure `/purge-api/etl` and `/purge-api/engine` reach the owners' internal purge APIs with their bearer tokens, so the `/dev/` purge-all covers every owner; the browser never holds a token. Upstreams are plain HTTP on internal ingress; TLS ends at the Container Apps ingress. Never carry the Docker resolver into Azure. `node frontend/devtools/test-proxy.ts` checks the rendered config for both modes.

## 2. Public demo API

*In short: five routes, no login, rate-limited.*

| Route | Methods | Limit (over it: `429`) |
| --- | --- | --- |
| `/demo-api/start`, `/demo-api/cancel`, `/demo-api/skip` | POST only | One shared limit for every viewer: 10/min, burst 5 |
| `/demo-api/state`, `/demo-api/status` | GET only | Per client (last `X-Forwarded-For` hop): 40/s, burst 200 |

nginx strips `Authorization` and proxies to demo control (`DEMO_CONTROL_UPSTREAM`, internal ingress, one replica kept warm). Without a reachable demo control `/demo-api/` returns `502` and the viewer hides Start demo. Contract: [local/contracts §7a](../../local/contracts/README.md#7a-demo-control-public).

## 3. Edge proxy

*In short: a custom hostname in front of the Container App.*

A Cloudflare Worker ([`edge-proxy/`](../../edge-proxy/README.md)) forwards every request at `msft-hackathon.koda-software.com` to the frontend's Azure FQDN (`UPSTREAM` in `wrangler.toml`; update it when a redeploy changes the FQDN). It adds no logic; nginx still does all routing and limits. Behind it, the per-client key is a Cloudflare edge node, which is why the read limit is high.
