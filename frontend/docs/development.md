# Develop the frontend

```sh
./dev up backend
```

Open **http://localhost:18020/** for the match viewer, or **http://localhost:18020/lab/** for the removable filter lab. Docker provides nginx, the backend, Postgres and separate fake upstream services. No Azure account is needed. The default fixture agent works without a model account; [optional local LLM](../../user-backend/docs/local-llm.md) enables flexible questions.

## Match viewer

A fresh database starts with the fictional Chelsea–Manchester United recording. Existing recordings are preserved. Select a demo profile, start the synthetic replay, and watch the match state, insights and five compact statistics. Raw events are shown only in the developer lab. In Questions, ask for a stat and select Track on the offered card. A tracked custom stat replaces a default slot; removing it restores that default. The original answer retains its as-of timestamp.

Replay controls are development controls for one shared match. Starting a new product demo loads Chelsea–Manchester United and affects all viewers. The optional simulator excerpt is illustrative and explicitly labelled as separate from the Chelsea–United events. Without the local media mount, the player shows an unavailable state. Rewind, clips and individual playback delay remain phase 2. Profile sessions are demo identities, not production authentication.

The browser talks only to the user backend. Static modules are independently cacheable; the viewer uses one WebSocket for match updates and HTTP for deliberate actions/questions. Connection recovery uses a fresh authoritative snapshot. It does not run an LLM loop, calculate statistics, or read an upstream database.

## Filter lab

Use `/lab/` to prepare a structured rule, inspect its JSON and replay a recording. Load JSON accepts a synthetic match file up to 2 MiB; an invalid file preserves the run. Use demo restores the original Chelsea/Madrid `filter-lab.json` recording. Download exports the selected recording. Event inspection only exposes received deliveries.

The lab retains its existing 700 ms development polling. It is separate from the push-based match viewer. New run and recording replacement affect the shared replay; don't run smoke tests during a demonstration because they reset it.

## Checks

```sh
cd frontend
npm test
```

Node 20+ is sufficient; the application has no bundled framework dependency. Run the [icon harness](../assets/README.md) separately. Backend regression/integration checks use `./dev test backend` and deliberately reset fixtures.

Browser acceptance: profile switch, replay, current bucket cards/backlog, a question while updates continue, explicit Track/Untrack, refresh, takeover, disconnection, keyboard controls and narrow mobile layout. Model/event content must stay text, never executable HTML. [Question contract](../../user-backend/docs/question-agent.md) · [Design and research](design-references.md).

## Deployment boundary

nginx is the local static server and same-origin proxy. Production can place static assets behind Azure Front Door/CDN and replace the socket transport with an authenticated delivery gateway or Azure Web PubSub adapter. Use Microsoft's supported recovery SDK for that adapter. Multiple backend replicas still need shared session ownership, durable delivery and coordinated match calculations; adding replicas to the development harness alone is insufficient.

## Files and caching

| Area | Responsibility |
|---|---|
| `match/api.js`, `live.js` | Same-origin requests and one reconnecting live connection |
| `match/controller.js` | Session and user-action coordination |
| `match/view.js`, `chat-view.js`, `dom.js` | Bounded, safe DOM rendering; preserve unchanged controls |
| `match/format.js` | Display formatting and bounded snapshot handling |
| `match/styles.css`, `companion.css` | Responsive Premier League integration presentation |
| `tools/build.sh` | Content-hashed static module directory, without a bundler |
| `nginx.conf` | Same-origin API/socket proxy, compression, headers and cache policy |

HTML revalidates; a build places related JS/CSS under one content hash and caches them immutably. Relative module imports stay in that version. The unversioned developer lab and brand assets revalidate. No application secrets or LLM keys are shipped.

Run `node frontend/benchmarks/client.mjs` from the repository root for opt-in static transfer and bounded state-update checks. This does not measure DOM rendering, network fan-out or viewer capacity.

## Optional simulator footage

Supply a local H.264 MP4 without adding it to Git or the Docker image:

```sh
DEMO_VIDEO_PATH=/absolute/path/to/simulator.mp4 docker compose \
  --env-file local/env.defaults -f local/compose.yaml -f local/compose.media.yaml \
  --profile backend up -d --no-deps frontend
```

Run from the repository root. The read-only mount serves `/media/simulator.mp4` directly through nginx with byte-range support. The footage loops silently with no seeking UI; Play/Pause only affects the illustrative footage, not fixture events. Reduced motion starts paused. This optional adapter (`match/video.js`) does not control the shared fixture replay. Removing the mount preserves the data-only demo.

The current local excerpt comes from an existing Google Research Football simulation (10:00–13:00 of the saved recording). It is **not Chelsea–United footage** and is not synchronized with the synthetic fixture. The user approved this temporary visual stand-in. Matching footage/event timing remains to be connected; production video would use a media delivery service/CDN, not user-backend fan-out.
