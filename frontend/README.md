# Frontend

[Run locally](docs/development.md) · [Design references](docs/design-references.md) · [Icon checks](assets/README.md) · [Verification](docs/verification.md)

![Live match, statistics and two conversation tabs](architecture.svg)

**Match viewer:** one live match, fixed stat slots, bucketed insights and a question tab. The stream-first layout reserves the main area for match footage, with five stat slots below and a compact Insights / Ask companion. An optional simulator excerpt illustrates the player; its footage is independent of the Chelsea–United fixture events. Clips and rewind remain phase 2. The separate filter lab stays at `/lab/`.

```text
Static HTML / CSS / modules ← CDN or nginx
             ↓ one live connection
User backend → match state + cards + narratives
             ↔ questions + Track / Untrack
```

- Choose either team or Neither, plus Analytical, Simple, Casual or Experienced. Chat and pins stay with the same demo identity; already-framed narratives come from upstream. Only combinations with connected viewers are enabled in the demo audience catalogue.
- Standard statistics come from ETL through the backend. The browser never calculates match statistics.
- Tracking a standard or custom stat replaces the lowest-priority default card; untracking restores the default.
- Questions keep their as-of snapshot while live cards advance. Sessions restore on refresh; a new session takes over the previous tab.

**Scale boundary:** static files can be distributed independently. One push connection per viewer, bounded UI state and shared backend projection avoid per-viewer polling or agent loops. The local single-process harness is not an EPL-capacity demonstration. [Production boundaries](../user-backend/docs/scaling.md).

[Repository plan](../README.md)
