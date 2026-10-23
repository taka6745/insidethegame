# devtools/

> **In short:** developer checks, never shipped: a contract mock, a headless browser check, the bundle deny-list scan, the nginx template check and the icon harness.

| File | Run | Checks |
| --- | --- | --- |
| `mock-server.ts` | `npm run build && node devtools/mock-server.ts 18099` | Serves `dist/` with the production CSP and an in-memory, synthetic mock of matches, sessions, WebSocket, follows, clips, lab and `/dev/` (`MOCK_NO_MODEL=1`: no model) |
| `headless-check.ts` | `node devtools/headless-check.ts http://127.0.0.1:18099 [--flow follow\|unavailable\|sting\|capture]` | 1440/390/360 px: overflow, console and CSP errors; `--flow` drives the follow chat, the reel sting or the clip cards |
| `check-bundle.ts` | `npm run check:bundle` | `dist/` names no deny-listed term; prints file names and counts only |
| `test-proxy.ts` | `docker build -t itg-frontend-proxy-test frontend && node frontend/devtools/test-proxy.ts` | Renders the nginx template with default and Azure-like settings, runs `nginx -T`, checks gates and header handling |
| `check_icons.py`, `test_icons.py`, `icon-requirements.txt` | [assets](assets.md#1-icon-harness) | Icon overlap and size budget |

The deny-list is never in the repository: set `BUNDLE_DENYLIST` (comma or newline separated) or keep one term per line in the ignored `.local/bundle-denylist.txt`. `npm test` runs the scan when both the list and `dist/` exist; CI runs it when the repository secret is set.

The mock has no `/demo-api/state` or `/feed-api/demo`, so the headless check reports those two 404s on `/` and `/dev/`.
