# Working in InsideTheGame

This hackathon application has a runnable user backend and frontend, plus a simulated match feed and a local Stream Analytics stand-in for the local stack. The Azure ETL pipeline (`etl/`) and the narrative engine (`narrative-engine/narrative_engine/`) are implemented and deployed to Azure with `./dev azure up` (demo build; open checks in PLAN.md §10.4). The judge demo (PLAN.md §10: Start demo, seeds, clips, cross-game) runs through `local/demo_control.py`; the judge URL is served by `edge-proxy/`. Active areas: `data-generation/`, `etl/`, `narrative-engine/`, `user-backend/`, `frontend/`, `local/`, `edge-proxy/`. Read each service's README before changing it.

- Keep code small, readable and reusable. Add implementation only when requested.
- Preserve local changes. Keep credentials in ignored files or approved secrets; never print or commit them.
- Keep READMEs short and graphical. Distinguish planned, implemented, tested and deployed work.
- The detailed sections of `legacy/design/plan.excalidraw`, plus later decisions in active docs, define the plan. Older sketches are historical.
- Preserve original example prompts in `narrative-engine/docs/design/example-prompts/`. Resolve their output contracts before implementation.
- The user backend owns audience definitions and exposes a read-only configuration API. The narrative engine reads those definitions and owns bucket framing. The user backend receives already-bucketed narratives and routes them without rewriting.
- User questions never trigger the shared narrative workflow. Narrative history uses the narrative service's GraphQL API; live narratives use Service Bus.
- Live match events reach the user backend through its own Event Hubs consumer group, for every match. History and computed stats use ETL GraphQL.
- ETL owns standard stat calculations; event history, stats and the stat catalogue live in its Azure SQL. The backend accesses them through ETL GraphQL, never direct DB connections. Reuse existing stats before generating custom calculations; ordinary cards must not fetch raw history or recalculate standard stats.
- User-specific code/calculations belong to `user-backend/`, with an isolated generated-code executor, not ETL.
- Test changed behaviour and inspect actual outputs. Design diagrams are not tested infrastructure.
- Label synthetic data and preserve provenance/licences. Do not execute archived competitor code.
- `legacy/` preserves research, scraping scripts, simulator code, earlier docs and outputs. It is inactive; do not revive its automation or overwrite it during application work.
- Preserve ignored `.local/` runtime environments and assets; do not upload them.

## Service layout and docs

Each implemented service uses the same top-level folders where they apply: `contracts/` (what consumers can rely on), `infra/` (Terraform), `tests/`, `docs/`, plus one folder per component whose name says what it holds. Developer-only code goes in `devtools/`.

Each service's `docs/` has the same pages: `README.md` (index tree), `overview.md`, `architecture.md`, `components/<one page per code folder>.md`, `development.md`, `deployment.md`, `decisions.md`, and `design/` for original design material that is no longer updated. Every page opens with an **In short** summary and a facts table; every numbered section opens with a one-line *In short*. See `etl/docs/` and `narrative-engine/docs/`. Docs live only in a service's `docs/` plus its one `README.md` (and `contracts/README.md`); root keeps `README.md`, `AGENTS.md`, `DEVELOPMENT.md`, `DEVELOPMENT-PRACTICES.md` and `PLAN.md`. Exception: `edge-proxy/` (one pass-through Worker) keeps a README only.

## Code organisation

Follow [DEVELOPMENT-PRACTICES.md](DEVELOPMENT-PRACTICES.md). New code separates models, services, repositories, adapters and HTTP/view layers. Routes call application services; repositories own DB connections. Event vendor keys stay in a replaceable adapter. Structured model output is validated data, never executable Python.

## Current tooling

Start with [DEVELOPMENT.md](DEVELOPMENT.md) and each service's `docs/development.md`.

- `./dev doctor`: Docker/Compose preflight. `./dev up` starts Postgres + Cosmos and runs checks; `./dev test` reruns them.
- `ACCEPT_EULA=Y ./dev up azure` / `./dev test azure`: Microsoft emulators, SQL and the ETL's DAB (read-only checks). Only set EULA acceptance with the developer's consent; see `local/README.md`.
- `./dev terraform check`: format/schema validation and mock-provider tests in Docker; no real Azure calls.
- `ACCEPT_EULA=Y ./dev up backend` / `./dev test backend`: real-Postgres API tests plus non-destructive probes (Event Hubs → etl-stream → SQL → ETL GraphQL and the backend, then purged). Microsoft emulator licences require each developer's acceptance. See `user-backend/docs/development.md`.
- `./dev demo start [fixture…]` / `./dev demo purge`: purge every match from every owner (feed → ETL → engine → backend), then start one feed run per fixture (default `riverton-forgeham`; also `redcastle-portalbion`, `skybridge-whitmore`) at the next whole minute, from 00:00, several at once. Configuration (profiles, audience templates with their enabled buckets, prompts, presentation, prices) stays. The feed simulates an external provider: Event Hubs `match-events` (MA1, MA3, POS, MatchEvent v2) and played HLS over HTTP.
- `./dev` mounts one media root (`ITG_MEDIA_ROOT`, default `.local/media/{fixture}/hls/`, hard-linked from `.local/grf-demo-{fixture}-90/hls/`) into the feed only; the feed has its own Postgres; the feed publishes played segments, nginx proxies `/media/hls/{matchId}/`. Media remains optional and ignored.
- Judge demo: the viewer's **Start demo** / **Cancel demo** call `demo-control` (`local/demo_control.py serve`, public `/demo-api/{start,cancel,skip,state,status}`; see `local/docs/components/demo-control.md`): always three fixtures, main game (`main_fixture`, default `redcastle-portalbion`) first. Seeds: `docker compose -p itg-local exec demo-control python /checks/demo_control.py record {point} [--from {point}]`, then `capture {point}`, into `.local/seeds/` (Azure Files on Azure).
- Demo-only seed adapter: export/restore routes on feed, ETL, engine and backend exist only with `DEMO_SEEDS=1` (local compose and the demo build). Core services never branch on a demo; `./dev azure up --release` leaves it off.
- `./dev benchmark replay`: replay golden set against the local model (`--agent fixture` runs the benchmark double).
- `./dev down`: stops only this Compose project, preserving database volumes.
- `python3 .github/scripts/render_architecture.py`, `render_development.py` and `render_master_plan.py` (writes `master-plan.excalidraw`; export it to `master-plan.svg` through Excalidraw, padding 40): regenerate the diagrams, render to PNG and visually inspect.

The feed and `etl-stream` are replaceable local stand-ins (for the provider and Stream Analytics), not production services. Older backend fixtures remain isolated test doubles, not the viewer's runtime upstreams. Never execute generated code inside the API; the local agent workflow interprets goals using Microsoft Agent Framework and compiles a bounded rule DSL deterministically; agent doubles live only in tests and benchmarks. An arbitrary-code isolated executor is still to build. Stream Analytics belongs to the ETL service. Keep Azure cloud deployment separate: `./dev azure up|down|status|plan [--release]` deploys every service with Terraform (see `terraform/docs/deployment.md`; production gaps and LATER notes in `terraform/docs/decisions.md`). Azure models: Foundry `gpt-6.1-sol` (deployments `writer` for the engine, `questions` for the backend, effort low; `gpt-6-luna` and `gpt-5-mini` selectable per role in `/dev/`) and `Microsoft-Decision-1` (claim checks, follow triggers, clips, follow offers). The spend guard (`terraform/guard`, applied first, kept by `down`) only emails on budgets, runs Stream Analytics only while events flow and has one last resort at 90 % of the credit. The edge proxy (`edge-proxy/`, `npx wrangler@4.151.3 deploy`) points `msft-hackathon.koda-software.com` at the frontend; update its `UPSTREAM` after a redeploy changes the FQDN. Do not run cloud apply as part of local setup.

Each service keeps its own Terraform (`terraform/guard`, `etl/infra/`, `narrative-engine/infra/`, `data-generation/infra/`, `terraform/` for the app and demo control); `./dev azure` applies them in order. Confirm with the developer before any `terraform apply`, and stop the ETL's Stream Analytics job after testing (it bills while running).

Archived commands may use old paths. Recheck official hackathon rules in `legacy/research/` before submission. `.github/workflows/ci.yml` runs every service's tests (no cloud or model calls); no scheduled scraping is configured.
