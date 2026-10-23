# lab/

> **In short:** the filter lab at `/lab/`: pick a live match, prepare a structured rule, inspect its JSON and the received events, and chat with the question agent. Developer-only; gated like `/dev/`.

| | |
| --- | --- |
| **Routes** | `/api/matches/{matchId}/…` (state with `seq`, `events/{seq}`, calculations, plan, chat); `/api/chat/profiles`; match list from `/viewer-api/matches` (never the feed) |
| **Polling** | Selected match every 700 ms, match list every 5 s |
| **Without a model** | Backend answers `503`; the lab shows "answers unavailable" and disables asking |

| Files | Responsibility |
| --- | --- |
| `api.ts`, `chat-api.ts` | `LabApi` and `ChatApi`; responses parsed by [`shared/http.ts`](shared.md) |
| `controller.ts`, `chat-controller.ts` | Polling, rule and chat coordination |
| `view.ts`, `chat-view.ts`, `format.ts`, `types.ts` | Rendering, formatting, payload types |

There is no recording upload, download or replay control.
