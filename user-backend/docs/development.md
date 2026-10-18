# Develop the user backend

![Service boundary](../architecture.svg)

**Own:** demo profiles, sessions, questions, stat cards, reusable match-scoped functions and viewer delivery.

```text
Profile + match/narrative APIs → viewer session → frontend
Question → agent → optional coding agent → isolated executor
```

**Start:** [Docker setup](../../DEVELOPMENT.md), then `./dev test`. `accounts` contains three demo profiles; `matchapp` is an empty application database. Use `./dev test azure` for independent event/message/GraphQL checks.

**Build next:** profile → bucket → history/current state, then the live connection. Consume Event Hubs using `user-backend`; receive `narratives` through its own subscription. Read narrative history through its API, never Cosmos. Add a question agent after this vertical slice works.

**Custom stats:** goal → code → semantic/result tests → up to three repairs → calculate → optional pin. Pins replace the lowest-priority default card. Reuse equivalent functions for this match. Execute generated code outside the API process; the sandbox is not implemented by this Docker setup.

**Prove it:** mid-match join, reconnect/session takeover, duplicates, custom-stat backfill/live handoff and pin replacement. One live match, one session/profile. Questions must not trigger narrative generation.

**Azure:** Container Apps, Agent Framework/Foundry, two PostgreSQL databases on one server. [Full decisions](../architecture.md). Jev, clips and playback-aware delivery remain Phase 2.
