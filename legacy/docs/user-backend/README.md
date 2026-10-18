# User backend canvas

Icon-led planning view of [architecture.md](architecture.md): the main user backend's services and how they connect to the match event pipeline (left), frontend (right) and neutral narrative engine (bottom). Phase 2 (Jev subscriptions, replay, playback-aware state) is grey and dashed at full opacity.

| File | Role |
| --- | --- |
| [canvas.json](canvas.json) | Zones, nodes (logo, name, short notes) and arrows |
| [build_canvas.ts](build_canvas.ts) | Generator; glyphs from `docs/icon-libraries/engineering.excalidrawlib`, captions dropped |
| [user-backend.excalidraw](user-backend.excalidraw) | Generated scene (356 elements, 26 arrows bound at both ends) |
| [user-backend.png](user-backend.png) | Preview, 2x |

Build: `bun run docs/user-backend/build_canvas.ts`, then import `user-backend.excalidraw` into the canvas (replace mode).

Screenshot-verified (whole canvas, then each region at 2x): no overlapping nodes or labels, text readable at 100% zoom, labels sit on their arrows, legend clear of the diagram.
