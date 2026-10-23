# match/

> **In short:** the viewer at `/`: picker, demo controls, live match, insights, questions, follows, clips and replays. Plain TypeScript modules, compiled to `dist/match/` and fingerprinted under `/app/{hash}/match/`.

| | |
| --- | --- |
| **Entry** | `index.html` → `main.ts` |
| **Talks to** | `/viewer-api/`, `/demo-api/`, `/media/hls/` ([architecture](../architecture.md#1-routes-the-viewer-calls)) |
| **Tests** | `tests/*.test.ts` (unit, DOM doubles), [headless check](devtools.md) |

## 1. Files

*In short: API, controller, views; one file per concern.*

| Files | Responsibility |
| --- | --- |
| `api.ts`, `live.ts` | Same-origin requests with viewer-safe errors (`friendly()`), one reconnecting live connection |
| `controller.ts` | Session and user-action coordination; match gone → picker |
| `viewer-id.ts` | Anonymous viewer id in `localStorage` (page-only when storage is blocked) |
| `picker.ts`, `branding.ts` | Match picker; club colours and crests from match data |
| `demo.ts`, `demo-progress.ts` | Start, Cancel and Skip ahead, start points, main game, "live from N′"; seven-stage start progress |
| `view.ts`, `audience-view.ts`, `chat-view.ts`, `clarification-view.ts` | Bounded, safe DOM rendering that keeps unchanged controls |
| `follow.ts`, `follow-view.ts` | Follow chat, suggestions, follow and stop following |
| `capture.ts` | Captured clips: one feed card per clip, preview built in the browser |
| `other-match.ts` | Cross-match marking: `otherMatchHeader`, `markOtherMatch` (yellow outline, teams and crests, no score) |
| `replay.ts`, `replay-card.ts`, `replay-view.ts` | Replay clips, chat card, stage and corner picture, sting and slow motion |
| `media.ts`, `video.ts`, `hold.ts` | Live HLS, stream states, data held to the picture |
| `receipt.ts` | Answer receipts costed at the backend's prices (offline cache only) |
| `format.ts`, `types.ts` | Display formatting, snapshot handling, payload types |
| `styles.css`, `companion.css` | Responsive match-centre presentation; companion motion (CSS only, off under reduced motion) |

## 2. Rules

*In short: text only, bounded, no secrets.*

- Model and event content is rendered as text, never HTML.
- No statistics are calculated and no model is called in the browser.
- No secrets or keys are shipped. Shared helpers come from [`shared/`](shared.md).
