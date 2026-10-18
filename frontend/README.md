# Frontend

[Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![Live match, statistics and two conversation tabs](architecture.svg)

**Planned interface; not implemented.** Show one live match with stat cards and two tabs: agent chat and the narrative feed/backlog.

- Select a demo profile; use its team and fan style to resolve the bucket.
- Send questions and pin/unpin actions to the user backend. Receive replies and live updates.
- A custom pin replaces the lowest-priority default card. Keep the slot count fixed.
- Restore chat and pins after reconnecting. A new session takes over the previous one.
- Mid-match viewers receive narrative history and current bucket stats.

**Boundary:** the browser talks to the user backend for application data, and to the footage source for video. It does not query databases or run agents.

**Azure / framework:** hosting and frontend framework are undecided. Live transport and card count are also open; diagram cards are illustrative.

**Phase 2** (grey/dashed): play requested clip segments, pause/rewind, and align stats and narratives with playback position. The backend returns source IDs and timestamps; the browser plays the segments.

[Repository plan](../README.md)
