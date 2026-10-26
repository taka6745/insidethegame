# Edge proxy

A Cloudflare Worker forwards the public hostname to the Azure frontend. Paths and queries pass through unchanged.

```text
browser → msft-hackathon.koda-software.com → Azure frontend → backend / video
```

| Task | Command or source |
| --- | --- |
| Deploy | `cd edge-proxy && npx wrangler@4.151.3 deploy` |
| Test | `cd frontend && npm test` includes the Worker's type check |
| Contract | One pass-through fetch: [src/index.ts](src/index.ts) |
| Configuration | [wrangler.toml](wrangler.toml); `./dev azure up` rewrites `UPSTREAM`, then redeploy the Worker |

The Worker is outside Terraform and survives `./dev azure down`. Azure ingress remains directly reachable. Behind Cloudflare, nginx's rate-limit key identifies an edge node ([frontend](../frontend/README.md#deployment)).
