# Develop the frontend

The **filter lab** is a removable client for testing backend calculations. The product UI in [the architecture](../architecture.svg) remains planned.

```text
Sample rule / user request → User backend → Structured calculation
Synthetic events          → User backend → Updated cards + event feed
```

Run `./dev up backend` from the repo root, then open **http://localhost:18020**. Choose sample filters or ask the local development model to prepare one. Inspect its JSON and add it before starting the replay. **Load JSON** replaces the recording and starts a fresh run with no rules. Files must be JSON and at most 2 MiB; validation failures preserve the current run. **Use demo** restores the default repository recording. **Download** exports the loaded JSON, while selecting a received event opens its raw and canonical payloads. The browser only requests payloads for received deliveries.

**New run** resets the lab; there is no rewind or video feed. Model access is optional: sample rules work without it.

| File | Responsibility |
|---|---|
| `lab/api.js` | Backend HTTP adapter; the only network calls |
| `lab/controller.js` | User actions and non-overlapping state polling |
| `lab/view.js` | DOM rendering, recording identity and payload/rule inspection |
| `lab/format.js` | Display-only formatting |
| `lab/styles.css` | Responsive layout |
| `nginx.conf` | Same-origin `/api/` proxy to backend `/lab/` |

**Boundary:** the browser never calculates statistics, queries ETL or opens a database connection. The backend owns filtering, indexing, state, model calls and replay. Replace the HTTP adapter to connect a future product interface; remove `lab/` and its Compose service when the stub is no longer needed.

Run small client tests with `cd frontend && npm test` (Node 20+; no npm install). Browser checks should cover adding a preset, preparing a rule, forward replay, changed cards, rule inspection, model/API errors and an explicit new run. Keep untrusted model/event content as text, never HTML.

The lab polls every 700 ms; this is a development transport, not the production live-delivery design. New runs and calculations share one lab session across connected browsers.
