# Develop the frontend

> **In short:** run the whole stack with `./dev up backend`, press Start demo at `localhost:18020`, and check changes with `npm test` plus the headless check against the contract mock.

| | |
| --- | --- |
| **Viewer** | `http://localhost:18020/` (picker, Start demo), `/lab/`, `/dev/` |
| **Source** | TypeScript in `match/`, `lab/`, `dev/`, `shared/`, `tests/`, `devtools/`, `benchmarks/`; shell in `tools/`; the icon harness in `devtools/` is Python; plain `.js` only in ignored `dist/` |
| **Node** | 22.18+ (runs `.ts` tests and tools directly by type stripping) |

## 1. Run locally

*In short: one command; no Azure account needed.*

```sh
ACCEPT_EULA=Y ./dev up backend
```

Open **http://localhost:18020/** and press **Start demo**, or run `./dev demo start [fixture…]`, or start runs from **/dev/** (Matches panel). Docker provides nginx, the feed (simulated external provider: recordings, runs, HLS origin), the ETL stand-in with its GraphQL, the narrative engine, demo control, the backend and Postgres. Questions and custom stats need a [model](../../user-backend/docs/components/agents.md); without one they show "answers unavailable" while insights and stats continue.

nginx re-resolves the backend through Docker DNS every five seconds, so a replaced backend container is found again; brief downtime shows a retryable error and the socket reconnects with a fresh snapshot.

## 2. Live footage

*In short: synthetic recordings of fictional clubs, proxied from the feed.*

The feed stands in for an external match provider: it writes each run's played segments and nginx proxies `/media/hls/{matchId}/…` to its HLS origin (`MEDIA_ORIGIN`, default `feed:8000`). Nothing is mounted into the frontend. The recordings are synthetic: fictional clubs and invented players on simulated (Google Research Football) play, never an actual match.

## 3. Checks

*In short: `npm test` for types and units; the headless check for layout and flows.*

```sh
cd frontend
npm ci
npm test               # tsc (also edge-proxy/src), then node --test on tests/*.test.ts
npm run build          # tsc → dist/ (compiled JS + copied HTML/CSS + hls.js)
npm run check:bundle   # dist/ names no deny-listed term
node devtools/mock-server.ts 18099 &
node devtools/headless-check.ts http://127.0.0.1:18099                  # 1440/390/360 px: overflow, console, CSP
node devtools/headless-check.ts http://127.0.0.1:18099 --flow follow    # follow, clarify, stop following
node devtools/headless-check.ts http://127.0.0.1:18099 --flow sting     # reel: hold → sting → cut → play
node devtools/headless-check.ts http://127.0.0.1:18099 --flow capture   # clip preview cards
MOCK_NO_MODEL=1 node devtools/mock-server.ts 18098 &                    # then --flow unavailable on that port
```

Details: [devtools](components/devtools.md). Icon harness: [assets](components/assets.md#1-icon-harness). Nginx template: `node frontend/devtools/test-proxy.ts` after `docker build -t itg-frontend-proxy-test frontend`. Backend integration: `./dev test backend`. CI runs `tsc`, `npm test`, `npm run build` and the bundle scan.

## 4. Browser acceptance

*In short: what to try by hand on the local stack.*

Start demo and Skip ahead; two tabs on two matches; purge returning a tab to the picker; audience changes; a question while updates continue; Track/Untrack; follow and stop following; clip Play with sting and slow motion; refresh, takeover and disconnect; keyboard controls and narrow mobile layout. Model and event content must stay text, never HTML.
