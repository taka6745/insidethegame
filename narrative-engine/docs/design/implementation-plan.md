# Narrative engine: implementation plan

Agreed 18 October 2026. Reconciles [narrative-generation-engine.md](narrative-generation-engine.md) with the [ETL contracts](../../../etl/contracts/README.md) as built. Where they differ, the ETL contracts and this plan win.

## Decisions

| Topic | Decision |
| --- | --- |
| Match time | Key on the ETL's Opta clock `(periodId, timeMin)`, 0-based; P1 added time continues (46 = `45+2'`), P2 restarts at 45. Display with the ETL's `minuteLabel` rule. |
| Notifications | Parse the ETL shapes: `MinuteClosed {periodId, timeMin, windowEnd}`, `KeyEventDetected` (a `keyEvents` row; `relatedEventId` may arrive as a string), `PeriodStarted`/`PeriodEnded`. Since 18 Oct every body carries every key (unused ones null); switch on body `messageType`. The Service Bus filter property is `notificationType`. |
| Half / full time | Driven by `PeriodEnded` 1 / 2. Extra time not supported in the demo. |
| Compression | §5.3 rules, counted within the current period only: blocks never span half time. When a period ends it collapses into one earlier block. Tested against the §5.4 checkpoints. |
| Quiet minutes | `MinuteClosed(t)` summarises every unsummarised minute up to t, in order. Empty minutes get a fixed block with no LLM call. Duplicates and late arrivals are no-ops. |
| No future leakage | Every ETL read is filtered as of the trigger's match clock: stats at `(periodId, timeMin)`, events by clock range, ledger up to now. |
| Fallback timer | Ten **match** minutes without a narrative step, evaluated on `MinuteClosed`. |
| Audience | Presence-driven, falling back to all 12. Proposed message: full state `{matchId, activeUserTypes: {bucket: count}, sentAt}` on change plus a 60 s heartbeat. All 12 if none received or last is older than 3 min. 0→1+ triggers a catch-up step for that bucket. Needs user-backend agreement. |
| Author output | Text only. Stat-selection instructions deferred. Summariser and compressor return `{"summary": ...}`. |
| Insight grouping | One `stepId` per trigger, shared by its bucket versions; `seq` per bucket. |
| Message handling | A message is recorded in the Cosmos checkpoint (closed minutes, horizon, queued steps) and completed at once; a worker per match does the model work from the checkpoint. Holding messages through LLM calls lost their one-minute locks (19 Oct). Steps run in match-time order with the horizon recorded with them, so a backlog gives the same narratives as live. Service Bus uses SAS keys for now: Contributor can't create RBAC role assignments (LATER: managed identity). |
| Narrative history | Strawberry GraphQL (ASGI, run by uvicorn) inside the engine container; no FastAPI. Chosen over Data API builder on Cosmos for local testability (no Cosmos emulator) and fields Cosmos doesn't hold, such as active buckets (19 Oct). Contract: [contracts/README.md](../../contracts/README.md). |
| Prompts | Originals in `docs/design/example-prompts/` stay unchanged; versioned runtime templates live in `narrative_engine/agents/prompts/`. |
| LLM (dev) | OpenAI-compatible hackathon API until 00:00 30 Oct 2026 (Brisbane); settings in ignored `narrative-engine/.env`. Per-role model settings. Validate JSON ourselves, one retry. Author concurrency ~4 with 429 backoff. Foundry replaced it for the deployed engine in phase 7. |
| LLM (Azure) | Foundry `gpt-5-mini` (GlobalStandard, 100K TPM) for all three roles, with `reasoning_effort` minimal for summaries and compression and low for the author (about 1.5 s per call). `gpt-4.1-mini` is marked Legacy. Called through Microsoft Agent Framework (`agent-framework-core` 1.22, chat completions client) on the OpenAI-compatible v1 endpoint, as in the design (20 Oct). Each agent has its own model, reasoning effort and optionally endpoint (`OPENAI_<SETTING>_<ROLE>`; Terraform `models` and `agents`), so the author can move to a stronger model alone. Agent Framework's OpenTelemetry traces and the engine's logs go to Application Insights (own workspace, 0.2 GB/day cap). Stat selection moved to the user backend. |
| Deployment | One Container App replica (each match's worker is in memory) in the ETL's Container Apps environment: the trial subscription allows one per region. Image built locally and pushed (`dev build --local`): ACR Tasks are not allowed on the trial. ACR admin credentials and Foundry key auth because Contributor can't create role assignments (LATER: managed identity). |
| Local mode | Replay `etl/.local/notifications.jsonl`, read local DAB on :5000, memory/JSON store, write `.local/narratives.jsonl`. No extra Docker images. |

## Phases

| # | Work | Status |
| --- | --- | --- |
| 1 | Pure core: models, message parsing, compression, prompt rendering; tests | Implemented, tested |
| 2 | Orchestrator end to end with fake agents, memory store, file source/sink, context builder | Implemented, tested |
| 3 | ETL GraphQL client (same interface as `FixtureMatchData`); no-leak test against DAB | Implemented, tested against a fake DAB and read-only against the Azure dev DAB (`itg-syn-0001-cloud*`): live tests pass, and a full fake-agent run gives the same narratives as the fixture run |
| 4 | Real agents on the dev API; inspect one full local match | Implemented, tested (mocked API) and run end to end: full synthetic match, 12 buckets, Azure dev GraphQL data, 192 narratives read through. Author prompt v2 cut premature "final whistle" lines (8 → 0) and invented xG (36 → 8, analyst buckets only) |
| 5 | Narrative GraphQL API; `contracts/README.md` | Implemented, tested in-process and over HTTP (serving a full LLM run, and live during a paced replay with `--serve`) |
| 6 | Service Bus and Cosmos adapters; dev Terraform (`infra/`: Cosmos serverless, `narratives` and `presence` topics) | Implemented, applied to dev, run live: ETL replay → Service Bus → engine (Cosmos, dev LLM API) → `narratives` topic and GraphQL. A restart mid-backlog resumed from the Cosmos checkpoint |
| 7 | Container App, image, Foundry, deploy | Implemented, deployed to dev (`itg-narrative-dev-engine`) and run live: full 10x replays narrated for all 12 buckets in step with the ETL. The first run lost one narrative (failed publish, stored but skipped on retry); fixed in v2, which republishes stored narratives on retry |
| 8 | README status | Planned |
