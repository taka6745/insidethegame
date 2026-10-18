# Frontend

[Run locally](docs/development.md) · [Design references](docs/design-references.md) · [Icon checks](assets/README.md) · [Verification](docs/verification.md)

![Live match, statistics and two conversation tabs](architecture.svg)

**Match viewer:** one live match, fixed stat slots, bucketed insights and a question tab. The event stage is labelled synthetic; video and rewind remain phase 2. The separate filter lab stays at `/lab/`.

```text
Static HTML / CSS / modules ← CDN or nginx
             ↓ one live connection
User backend → match state + cards + narratives
             ↔ questions + Track / Untrack
```

- A demo profile selects the team/style audience. Already-framed narratives come from upstream.
- Standard statistics come from ETL through the backend. The browser never calculates match statistics.
- Custom tracking replaces the lowest-priority default card; untracking restores the default.
- Questions keep their as-of snapshot while live cards advance. Sessions restore on refresh; a new session takes over the previous tab.

**Scale boundary:** static files can be distributed independently. One push connection per viewer, bounded UI state and shared backend projection avoid per-viewer polling or agent loops. The local single-process harness is not an EPL-capacity demonstration. [Production boundaries](../user-backend/docs/scaling.md).

[Repository plan](../README.md)
