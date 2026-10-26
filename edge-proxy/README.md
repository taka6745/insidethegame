# Edge proxy

A Cloudflare Worker that serves the demo at `msft-hackathon.koda-software.com` by proxying every request, path and query unchanged, to the Azure frontend (`UPSTREAM` in `wrangler.toml`). One pass-through `fetch` in [`src/index.ts`](src/index.ts); type-checked by the frontend's `npm test`.

```text
browser ─▶ msft-hackathon.koda-software.com (Cloudflare Worker) ─▶ Azure frontend (nginx) ─▶ backend · demo control · feed HLS
```

| | |
| --- | --- |
| **Deploy** | `cd edge-proxy && npx wrangler@4.151.3 deploy`; Cloudflare creates the DNS record and certificate |
| **Upstream** | The frontend's Container Apps FQDN; `./dev azure up` rewrites it after a redeploy changes it, then redeploy the Worker |
| **Not covered** | Outside Terraform and `./dev azure down`; Azure's own ingress stays reachable directly |

Behind the Worker, nginx's per-client rate-limit key (the last `X-Forwarded-For` hop) is a Cloudflare edge node, which is why the viewer's read limit is high ([frontend](../frontend/README.md#deployment)).
