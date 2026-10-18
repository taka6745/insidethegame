# Develop the frontend

![Service boundary](../architecture.svg)

**Own:** one live match, a fixed set of stat cards, agent chat and narrative tabs.

```text
User backend → profile / cards / chat / narratives
Footage source → live video
```

**Start:** read [backend decisions](../../user-backend/architecture.md) and [integration contracts](../../local/contracts.md). Shared Docker dependencies can run now; no frontend dev server exists yet. Choose the frontend framework and backend live transport before adding a Dockerfile and run command.

**Build next:** use clearly labelled response fixtures for the profile picker, cards and two tabs. Replace fixtures with the backend API once its contract exists. Keep all application data access through that backend.

**Prove it:** mid-match backlog; replacing the lowest-priority card; unpin restores a default; new tab takes over; reconnect restores chat/pins. Show waiting/error states while the coding agent works. Keep demo playback live.

**Azure:** hosting still undecided; the browser never holds database credentials or calls Foundry directly. Clips, rewind and semantic follows are Phase 2, not working controls in the first demo.
