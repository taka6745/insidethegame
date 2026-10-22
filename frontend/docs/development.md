# Develop the frontend

> **In short:** run the whole stack with `./dev up backend`, press Start demo at `localhost:18020`, and check changes with `npm test` plus the headless check against the contract mock.

| | |
| --- | --- |
| **Status** | Implemented · unit-tested · headless-checked (follow, sting, capture flows) · D1–D7 run on the local stack 22 Oct |
| **Viewer** | `http://localhost:18020/` (picker, Start demo), `/lab/`, `/dev/` |
| **Source** | TypeScript in `match/`, `lab/`, `dev/`, `tools/`; compiled to ignored `dist/` |

```sh
ACCEPT_EULA=Y ./dev up backend
```

Then `./dev demo start [fixture…]`, or start runs from **http://localhost:18020/dev/** (Matches panel). Open **http://localhost:18020/** for the match picker and viewer, or **/lab/** for the filter lab. Docker provides nginx, the feed (simulated external provider: recordings, runs, HLS origin), the ETL pipeline stand-in with its GraphQL, the narrative engine, the backend and Postgres. No Azure account is needed. Questions and custom stats need the [local model](../../user-backend/docs/components/agents.md); without one they show “answers unavailable” while insights and stats continue.

## Start demo

Press **Start demo** on the picker (start point: kickoff, or a recorded seed at 20′, HT, 60′, 85′; unrecorded points are disabled) or `./dev demo start`. The picker calls `/demo-api/start`, shows the seven-stage start progress (Feed → Event Hubs → ETL → Service Bus → Narrative engine → Backend → Viewer, each lit by `/demo-api/status`; reduced motion respected), then opens the main game. **Cancel demo** purges everything and returns to the picker. Recording seeds is a demo-control job (PLAN.md §10.6), not a viewer action.

## Match viewer

**Multi-match.** `/` lists matches from `GET /viewer-api/matches` (live, then scheduled, then finished) with status, score and clock, refreshed every 5 s. Opening one loads `/?match={matchId}`; each tab holds one match, so two tabs can watch two matches. Sessions are stored per (match, profile). A 404 for the match or socket close `4404` sends the tab back to the picker with a notice. A link opened before the match's MA1 (`404 match_not_started`) waits and retries every 5 s; a `scheduled` match shows teams and branding with a kick-off countdown and goes live with the first event. Team names, colours and crests come from the listing or snapshot (MA1 branding); a missing crest file falls back to the three-letter code. The header dropdown lists the match's enabled audience buckets; insights, Track/Untrack and the as-of rules are unchanged.

Matches start from `/dev/` (or `./dev demo start`), never from the viewer: the viewer has no replay controls. Profile sessions are demo identities, not production authentication. Audience buckets are configuration: the narrative engine writes only for buckets enabled in the fixture's template (`/dev/`), the viewer's dropdown offers exactly those, and each narrative is shown once the video reaches its clock.

The browser talks only to the user backend. Static modules are independently cacheable; the viewer uses one WebSocket for match updates and HTTP for deliberate actions/questions. Connection recovery uses a fresh authoritative snapshot. It does not run an LLM loop, calculate statistics, or read an upstream database.

## Filter lab

Use `/lab/` to select a match with live events, prepare a structured rule, inspect its JSON and the received events. Lab routes are `/api/matches/{matchId}/…` (state with `seq`, `events/{seq}`, calculations, plan, chat; `/api/chat/profiles` is global); the match list comes from the backend listing, never the feed. With no model configured the backend refuses questions and plans (503): the viewer and lab show “answers unavailable” and disable asking, while insights and stats continue. There is no recording upload, download or replay control.

The lab polls the selected match every 700 ms and the match list every 5 s. It is separate from the push-based match viewer.

## Checks

```sh
cd frontend
npm ci
npm test        # tsc type check, then node --test on tests/*.test.ts
npm run build   # tsc → dist/ (compiled JS + copied HTML/CSS)
npm run check:bundle   # dist/ must not name any deny-listed provider or model
node tools/mock-server.ts 18099 &   # contract mock: matches, sessions, WS, lab, /dev/, feed console
node tools/headless-check.ts http://127.0.0.1:18099   # 1440/390/360 px: overflow, console and CSP errors
node tools/headless-check.ts http://127.0.0.1:18099 --flow follow   # also drives follow, clarify and stop following
node tools/headless-check.ts http://127.0.0.1:18099 --flow sting    # reel: hold → sting → cut → play
node tools/headless-check.ts http://127.0.0.1:18099 --flow capture  # captured-clip preview cards in Insights and the follow view
MOCK_NO_MODEL=1 node tools/mock-server.ts 18098 &   # then --flow unavailable on that port: chat refused, chips still follow
```

The bundle deny-list is never in the repository: set `BUNDLE_DENYLIST` (comma or newline separated) or keep one term per line in the ignored `.local/bundle-denylist.txt`. The check prints file names and counts only. `npm test` runs it when both the list and `dist/` exist.

Source is TypeScript (`match/`, `lab/`, `dev/`, `tests/`, `tools/`, `benchmarks/`); plain `.js` exists only in ignored `dist/`. Node 22.18+ runs `.ts` tests and tools directly (type stripping). The only runtime dependency is exact-pinned `hls.js`; there is no bundler or framework. Run the [icon harness](../assets/README.md) separately. Backend regression/integration checks use `./dev test backend`; isolated tests use fixture doubles.

Browser acceptance: two tabs on two matches, purge returning a tab to the picker, audience bucket changes, current bucket cards/backlog, a question while updates continue, explicit Track/Untrack, refresh, takeover, disconnection, keyboard controls and narrow mobile layout. Model/event content must stay text, never executable HTML. [Question contract](../../user-backend/docs/components/agents.md#2-question-agent) · [Design and research](design-references.md).

## Deployment boundary

nginx is the local static server and same-origin proxy. It re-resolves the backend through Docker DNS every five seconds so a backend container replacement does not leave it pointing at a stale IP. Brief downtime still shows a retryable error; the socket reconnects with a fresh snapshot.

Production can place static assets behind Azure Front Door/CDN and replace the socket transport with an authenticated delivery gateway or Azure Web PubSub adapter. Use Microsoft's supported recovery SDK for that adapter. Multiple backend replicas still need shared session ownership, durable delivery and coordinated match calculations; adding replicas to the development harness alone is insufficient.

## Files and caching

| Area | Responsibility |
|---|---|
| `match/api.ts`, `live.ts` | Same-origin requests and one reconnecting live connection |
| `match/controller.ts` | Session and user-action coordination; match gone → picker |
| `match/picker.ts`, `branding.ts` | Match picker; club colours/crests from match data |
| `match/demo.ts`, `demo-progress.ts` | Start/Cancel demo, start points, main game, "live from N′" note; seven-stage start progress |
| `match/capture.ts` | Captured clips (D6–D7): one feed card per clip with a browser-built preview (gradient, crest, minute, event, player, score after) |
| `match/other-match.ts` | Cross-game marking (D5): `otherMatchHeader`, `markOtherMatch` (yellow outline, teams and crests, no score) |
| `dev/matches.ts`, `config.ts` | Feed runs (start, purge) and config-table editors |
| `dev/audiences.ts`, `profiles.ts` | Audience template editor (layers, options, enabled buckets) and demo-profile editor; revision-checked |
| `match/receipt.ts` | Answer receipts costed at the backend's configured prices (offline cache only) |
| `match/view.ts`, `audience-view.ts`, `chat-view.ts`, `dom.ts` | Bounded, safe DOM rendering; preserve unchanged controls |
| `match/format.ts`, `types.ts` | Display formatting, bounded snapshot handling and payload types |
| `match/styles.css`, `companion.css` | Responsive league match-centre presentation |
| `match/media.ts`, `video.ts`, `hold.ts` | Live HLS source selection and data held to the live picture |
| `match/replay.ts`, `replay-card.ts`, `replay-view.ts` | Replay clip navigation, chat card and stage/PiP view; reel transitions (sting) and slow motion from each replay's `playback` |
| `match/follow.ts`, `follow-view.ts` | Story follows: follow chat, suggestions, follow and stop following; feed rendering is in `view.ts` |
| `tools/build.sh` | Content-hashed static module directory from `dist/`, without a bundler |
| `tools/vendor.sh` | Copies the pinned hls.js light ES module and licence into `dist/match/vendor/` |
| `nginx.conf` | Same-origin API/socket proxy, per-match HLS proxy, gated dev consoles, headers and cache policy |
| `tools/check-bundle.ts`, `mock-server.ts`, `headless-check.ts` | Bundle deny-list check, contract mock, headless layout/console/CSP check |

The image compiles TypeScript in a Node build stage; nginx serves only the compiled output. HTML revalidates; a build places related JS/CSS under one content hash and caches them immutably. Relative module imports stay in that version. The unversioned developer lab and brand assets revalidate. No application secrets or LLM keys are shipped.

Run `npm run build` in `frontend`, then `node frontend/benchmarks/client.ts` from the repository root, for opt-in static transfer and bounded state-update checks. This does not measure DOM rendering, network fan-out or viewer capacity.

## Live footage

The feed stands in for an external match provider. It writes each run's played segments and nginx proxies `/media/hls/{matchId}/{playlist or segment}.m3u8|.ts` to its HLS origin (`MEDIA_ORIGIN`, default `feed:8000`, path `/hls/{matchId}/…`), as a CDN would. Nothing is mounted into the frontend; any other `/media/` path is `404`, and there is no MP4. Playlists are `no-cache`, segments immutable. Until the playlist's first segment plays the viewer shows "Starting the stream…" and retries every `STREAM_RETRY_MS`; it shows its unavailable state when the match has no stream, or once a live or finished match's playlist has stayed unplayable for `STREAM_START_WAIT_MS` (`match/video.ts`; before kick-off it keeps waiting). Live footage follows the published edge, opens paused at the final picture after full time and does not allow independent seeking.

The recordings are synthetic: real club and player names on simulated (Google Research Football) play, never an actual match. Production footage should use a media delivery service/CDN, not user-backend fan-out.

## Live HLS and replay

**Implemented, unit-tested and browser-verified against live HLS on 20 October 2026** (card, main-stage playback with live picture-in-picture, clip jump, back to live, paging, refine offer, saved-in-chat restore).

- When `match.media.url` names an `.m3u8` the viewer plays it (the match's own `/media/hls/{matchId}/live.m3u8`; no fallback playlist) with hls.js (`enableWorker: false`, live sync three segments, fixed target after stalls). `liveCatchUp` returns a playing picture to that target: 1.1× speed when more than 1.5 s behind, or one seek to the sync position after 3 s more than 6 s behind, then a 10 s cooldown, falling back to native HLS only where hls.js is unsupported. Otherwise no footage is requested.
- hls.js 1.7.3 (light ES build, Apache-2.0) is copied by `npm run build` into the hashed app directory and loaded on demand from the same origin. No CDN or worker is used.
- Live states with `media.seconds` wait in a bounded queue until the live playhead reaches that time. A stall or catch-up seek keeps holding at the current position. They are released immediately when no live picture is playing or the stream failed, and after at most 15 s.
- Replay replies render a chat card: clip count, length, captions, derived definition, refine offer, Play, and Previous/Show more paging (`GET M/sessions/{token}/turns/{id}/replay/{page}`). Without a playlist, Play is disabled and footage is marked unavailable. Restored turns render the same card.
- Play loads the match's published playlist into a second stage player and steps through `playlist_start`/`playlist_end`. Live continues as a muted corner picture; the picture, **Back to live** or Esc returns. Cards and Insights stay live.
- CSP allows `blob:` only in `media-src`, for hls.js's Media Source; every request is same-origin.

## Proxy deployment settings

The image renders nginx configuration at startup. `BACKEND_UPSTREAM` defaults to `backend:8000`; `NGINX_RESOLVER` defaults to Docker's `127.0.0.11`; `MEDIA_ORIGIN` (the provider's HLS origin) to `feed:8000`. Developer consoles are off unless `ENABLE_DEV_ADMIN=1` (local Compose sets it): `/feed-api/` → `FEED_ADMIN_UPSTREAM` (`feed:8000`), `/purge-api/etl|engine|backend` → `ETL_ADMIN_UPSTREAM` (`etl-stream:8000`), `ENGINE_ADMIN_UPSTREAM` (`narrative-live:8000`) and the backend's `/admin/matches/purge` (POST only); `/dev-api/`, the `/lab/` page and its `/api/` are gated the same way. On a public deployment enable them only with `DEV_ADMIN_PASSWORD` set ([deployment](deployment.md)); the basic-auth header is never forwarded upstream. Set both to the real reachable HTTP backend host/port and DNS resolver outside Compose. Never carry the Docker resolver into Azure. The configured upstream uses HTTP; terminate ingress TLS at the trusted gateway and provide a private route to the backend. A TLS-only upstream needs a separate HTTPS proxy configuration with certificate verification.

Check the actual image template with `docker build -t itg-frontend-proxy-test frontend` then `node frontend/tools/test-proxy.ts` from the root. The opt-in Docker check renders both defaults and custom settings, runs `nginx -T`, and verifies native nginx variables survive substitution. See [cloud prerequisites](../../terraform/deployment-readiness.md).
