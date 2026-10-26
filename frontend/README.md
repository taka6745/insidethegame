# Frontend

Watch a match, ask questions, follow a story and replay its moments. Static TypeScript behind nginx; the backend supplies all statistics and AI output.

![Viewer, live data and conversations](architecture.svg)

## What a viewer sees

| Screen | Does |
| --- | --- |
| `/` | Match selection |
| Match | HLS video, five stat cards, audience commentary, chat and story follows |
| Replays | Clip previews, slow motion and cross-match reels; live video continues in a corner |
| `/dev/`, `/lab/` | Gated configuration and filter tools; never part of the viewer flow |

## Contracts

See [local/README.md Contracts §6–8d](../local/README.md#6-live-media-hls): HLS, sessions, questions, follows and replays.

- One WebSocket supplies state; HTTP handles actions. Reconnect restores a snapshot.
- Data waits for the picture; questions carry the displayed `seq`.
- Model text is rendered as text. Secrets stay behind nginx.
- Profiles do not provide authentication; viewer capacity is unmeasured.

Source: [viewer](match/), [shared UI](shared/), [proxy routes](nginx.conf), [configuration](tools/nginx-setup.envsh).

## Development

From the repository root, run `ACCEPT_EULA=Y ./dev up backend` after consenting to the emulator licences ([local setup](../local/README.md#run-it)); open [localhost:18020](http://localhost:18020/).

From `frontend/` with Node 22.18+:

```sh
npm ci
npm test
npm run build
npm run check:bundle
```

Browser checks: run `node devtools/mock-server.ts 18099`, then in another terminal `node devtools/headless-check.ts http://127.0.0.1:18099`. The [harness](devtools/headless-check.ts) also covers follow, capture, sting and unavailable-model flows. Validate the running stack separately: questions, follows, replays, reconnect and mobile layout.

## Assets

Original fictional-league artwork; Microsoft attribution and licences in [provenance](assets/league/PROVENANCE.md). Icons have a [visual check](devtools/check_icons.py); hls.js is pinned and served locally.

## Deployment

[Terraform](../terraform/README.md) runs nginx as the public Container App behind the [edge proxy](../edge-proxy/README.md). Internal services remain behind same-origin routes. The proxy's rate-limit key identifies a Cloudflare edge node, not an individual viewer.

## Decisions

`tsc` plus fingerprinted assets keeps delivery simple. Same-origin HLS supports a strict CSP. No per-viewer live rewind; multi-replica delivery needs [backend coordination](../user-backend/README.md#limits).
