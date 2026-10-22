# Edge proxy

> **In short:** a Cloudflare Worker that serves the judge build at `msft-hackathon.koda-software.com` by proxying every request to the Azure web app (`UPSTREAM`). Deploy with `npx wrangler@4.151.3 deploy` from this folder; Cloudflare creates the custom-domain DNS record and certificate.

| | |
| --- | --- |
| Status | Deployed 22 Oct 2026 |
| Upstream | `UPSTREAM` in `wrangler.toml` (the Azure web app FQDN; update after a redeploy changes it) |
| Code | [`src/index.ts`](src/index.ts): path and query passed through unchanged, so `/`, `/viewer-api/`, `/demo-api/` and `/media/hls/` all reach the frontend's nginx |
| Tested | Deployed 22 Oct; no unit tests (one pass-through `fetch`) |
| Not covered | Outside Terraform and `./dev azure down`; Azure's own ingress stays reachable directly |

```text
browser ─▶ msft-hackathon.koda-software.com (Cloudflare Worker) ─▶ Azure frontend (nginx) ─▶ backend · demo control · feed HLS
```
