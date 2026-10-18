# Develop the frontend

```sh
ACCEPT_EULA=Y ./dev up backend
```

Open **http://localhost:18020/** for the match viewer, or **http://localhost:18020/lab/** for the removable filter lab. Docker provides nginx, the backend, Postgres, standalone recorded-match ETL and the narrative stub. No Azure account is needed. The default fixture agent works without a model account; [optional local LLM](../../user-backend/docs/local-llm.md) enables flexible questions.

## Match viewer

A fresh database starts with the committed synthetic Chelsea–Manchester United GRF recording. Existing runs are preserved; `./dev reset backend` explicitly loads a fresh run from ETL. Choose a team and viewer style in the header, start the synthetic replay, and watch the match state, insights and five compact statistics. All 12 combinations are selectable. Changes preserve chat and pins, and persist for the current demo identity and match run. Raw events are shown only in the developer lab. Insights displays [144 manually authored narratives](../../narrative-engine/fixtures/README.md) from the narrative service without rewriting them: one version per bucket for each of the twelve video minutes, released only after the matching events. Neutral recap tiers remain available separately for questions. In Questions, ask for a stat and select Track on the offered card. A tracked standard or custom stat replaces a default slot; removing it restores that default. Standard values stay owned by ETL, and a pinned default is not shown twice. The original answer retains its as-of timestamp.

Replay controls are development controls for one shared match. Starting a new product demo loads Chelsea–Manchester United and affects all viewers. The optional twelve-minute GRF video is aligned to the Chelsea–United events, with six video minutes per half and a displayed 90-minute football clock. Without the local media mount, the player shows an unavailable state. Rewind, clips and individual playback delay remain phase 2. Profile sessions are demo identities, not production authentication. The viewer retains its existing demo identity internally; the audience controls edit its match preference. Connected audiences enable their combinations in the backend catalogue; unused combinations stay stored but disabled. The narrative stub reads those targets to select existing authored versions; the future generator will use them before authoring.

The browser talks only to the user backend. Static modules are independently cacheable; the viewer uses one WebSocket for match updates and HTTP for deliberate actions/questions. Connection recovery uses a fresh authoritative snapshot. It does not run an LLM loop, calculate statistics, or read an upstream database.

## Filter lab

Use `/lab/` to prepare a structured rule, inspect its JSON and replay a recording. Load JSON accepts a synthetic match file up to 2 MiB; an invalid file preserves the run. Use demo restores the original Chelsea/Madrid `filter-lab.json` recording. Download exports the selected recording. Event inspection only exposes received deliveries.

The lab retains its existing 700 ms development polling. It is separate from the push-based match viewer. New run and recording replacement affect the shared replay; don't run smoke tests during a demonstration because they reset it.

## Checks

```sh
cd frontend
npm test
```

Node 20+ is sufficient; the application has no bundled framework dependency. Run the [icon harness](../assets/README.md) separately. Backend regression/integration checks use `./dev test backend`: isolated tests use fixture doubles, and the live checkpoint check leaves the active replay position unchanged. Separate lab smoke tests can still reset shared state.

Browser acceptance: team/style changes, replay, current bucket cards/backlog, a question while updates continue, explicit Track/Untrack, refresh, takeover, disconnection, keyboard controls and narrow mobile layout. Model/event content must stay text, never executable HTML. [Question contract](../../user-backend/docs/question-agent.md) · [Design and research](design-references.md).

## Deployment boundary

nginx is the local static server and same-origin proxy. It re-resolves the backend through Docker DNS every five seconds so a backend container replacement does not leave it pointing at a stale IP. Brief downtime still shows a retryable error; the socket reconnects with a fresh snapshot.

Production can place static assets behind Azure Front Door/CDN and replace the socket transport with an authenticated delivery gateway or Azure Web PubSub adapter. Use Microsoft's supported recovery SDK for that adapter. Multiple backend replicas still need shared session ownership, durable delivery and coordinated match calculations; adding replicas to the development harness alone is insufficient.

## Files and caching

| Area | Responsibility |
|---|---|
| `match/api.js`, `live.js` | Same-origin requests and one reconnecting live connection |
| `match/controller.js` | Session and user-action coordination |
| `match/view.js`, `audience-view.js`, `chat-view.js`, `dom.js` | Bounded, safe DOM rendering; preserve unchanged controls |
| `match/format.js` | Display formatting and bounded snapshot handling |
| `match/styles.css`, `companion.css` | Responsive Premier League integration presentation |
| `tools/build.sh` | Content-hashed static module directory, without a bundler |
| `nginx.conf` | Same-origin API/socket proxy, compression, headers and cache policy |

HTML revalidates; a build places related JS/CSS under one content hash and caches them immutably. Relative module imports stay in that version. The unversioned developer lab and brand assets revalidate. No application secrets or LLM keys are shipped.

Run `node frontend/benchmarks/client.mjs` from the repository root for opt-in static transfer and bounded state-update checks. This does not measure DOM rendering, network fan-out or viewer capacity.

## Optional aligned footage

`ACCEPT_EULA=Y ./dev up backend` automatically mounts `.local/grf-demo-chelsea-united-v2/match.mp4` if it exists. The video is ignored, not downloaded on setup, and not included in the image or Git. To use the matching MP4 stored elsewhere:

```sh
DEMO_VIDEO_PATH=/absolute/path/to/match.mp4 ACCEPT_EULA=Y ./dev up backend
```

Run from the repository root. The read-only mount serves `/media/simulator.mp4` directly through nginx with byte-range support. Use the MP4 packaged with the same [GRF recording](../../data-generation/docs/grf-demo.md); an arbitrary video will not align with its events.

The backend's shared replay clock drives `match/video.js`. Aligned footage starts/resumes with replay, corrects drift on new clock anchors, pauses on disconnect and stops at full-time. It does not loop or allow independent seeking. Browser autoplay restrictions may require a click or Enter/Space. Removing the mount preserves the data-only demo and shows the unavailable-player state. Rewind, clips and per-viewer delayed playback remain phase 2.

The recording is simulated football with illustrative named lineups and generic abilities, not an actual Premier League fixture. Production footage should use a media delivery service/CDN, not user-backend fan-out.

## Proxy deployment settings

The image renders nginx configuration at startup. `BACKEND_UPSTREAM` defaults to `backend:8000`; `NGINX_RESOLVER` defaults to Docker's `127.0.0.11`. Set both to the real reachable HTTP backend host/port and DNS resolver outside Compose. Never carry the Docker resolver into Azure. The configured upstream uses HTTP; terminate ingress TLS at the trusted gateway and provide a private route to the backend. A TLS-only upstream needs a separate HTTPS proxy configuration with certificate verification.

Check the actual image template with `docker build -t itg-frontend-proxy-test frontend` then `node frontend/tools/test-proxy.mjs` from the root. The opt-in Docker check renders both defaults and custom settings, runs `nginx -T`, and verifies native nginx variables survive substitution. See [cloud prerequisites](../../terraform/deployment-readiness.md).
