# Working in InsideTheGame

This hackathon application has a runnable user backend and frontend, plus recorded-match ETL and authored narrative stand-ins for the local stack. The Azure ETL pipeline (`etl/`) and the narrative engine (`narrative-engine/narrative_engine/`) are implemented and deployed to dev. Active areas: `data-generation/`, `etl/`, `narrative-engine/`, `user-backend/`, `frontend/`. Read each service's README before changing it.

- Keep code small, readable and reusable. Add implementation only when requested.
- Preserve local changes. Keep credentials in ignored files or approved secrets; never print or commit them.
- Keep READMEs short and graphical. Distinguish planned, implemented, tested and deployed work.
- The detailed sections of `legacy/design/plan.excalidraw`, plus later decisions in active docs, define the plan. Older sketches are historical.
- Preserve original example prompts in `narrative-engine/docs/design/example-prompts/`. Resolve their output contracts before implementation.
- The user backend owns audience definitions and exposes a read-only configuration API. The narrative engine reads those definitions and owns bucket framing. The user backend receives already-bucketed narratives and routes them without rewriting.
- User questions never trigger the shared narrative workflow. Narrative history uses the narrative service's GraphQL API; live narratives use Service Bus.
- Live match events reach the user backend through one shared Event Hubs consumer for the demo match. History and computed stats use ETL GraphQL.
- ETL owns standard stat calculations and stores current stats in its Cosmos DB; event history stays in ETL Azure SQL. The backend accesses both through ETL GraphQL, never direct DB connections. Reuse existing stats before generating custom calculations; ordinary cards must not fetch raw history or recalculate standard stats.
- User-specific code/calculations belong to `user-backend/`, with an isolated generated-code executor, not ETL.
- Test changed behaviour and inspect actual outputs. Design diagrams are not tested infrastructure.
- Label synthetic data and preserve provenance/licences. Do not execute archived competitor code.
- `legacy/` preserves research, scraping scripts, simulator code, earlier docs and outputs. It is inactive; do not revive its automation or overwrite it during application work.
- Preserve ignored `.local/` runtime environments and assets; do not upload them.

## Service layout and docs

Each implemented service uses the same top-level folders where they apply: `contracts/` (what consumers can rely on), `infra/` (Terraform), `tests/`, `docs/`, plus one folder per component whose name says what it holds. Developer-only code goes in `devtools/`.

Each service's `docs/` has the same pages: `README.md` (index tree), `overview.md`, `architecture.md`, `components/<one page per code folder>.md`, `development.md`, `deployment.md`, `decisions.md`, and `design/` for original design material that is no longer updated. Every page opens with an **In short** summary and a facts table; every numbered section opens with a one-line *In short*. See `etl/docs/` and `narrative-engine/docs/`.

## Code organisation

Follow [DEVELOPMENT-PRACTICES.md](DEVELOPMENT-PRACTICES.md). New code separates models, services, repositories, adapters and HTTP/view layers. Routes call application services; repositories own DB connections. Event vendor keys stay in a replaceable adapter. Structured model output is validated data, never executable Python.

## Current tooling

Start with [DEVELOPMENT.md](DEVELOPMENT.md) and each service's `docs/development.md`.

- `./dev doctor`: Docker/Compose preflight. `./dev up` starts Postgres + Cosmos and runs checks; `./dev test` reruns them.
- `ACCEPT_EULA=Y ./dev up azure` / `./dev test azure`: Microsoft emulators, SQL and DAB. Only set EULA acceptance with the developer's consent; see `local/README.md`.
- `./dev terraform check`: format/schema validation and mock-provider tests in Docker; no real Azure calls.
- `ACCEPT_EULA=Y ./dev up backend` / `./dev test backend`: real-Postgres API tests plus a non-destructive Event Hubs → ETL → Service Bus → narrative round trip. Microsoft emulator licences require each developer's acceptance. ETL uses separate local PostgreSQL history/stat databases; the narrative stub uses SQLite. See `user-backend/docs/testing.md`.
- `./dev reset backend` / `./dev replay backend`: create a fresh match run, then start the aligned 12-minute Chelsea–United GRF recording. Account profiles remain; match-scoped chat, pins and calculations start fresh. The narrative stub serves 144 manually authored versions (12 video minutes × 12 buckets), bound to this recording. Live events and snapshot watermarks use the Microsoft Event Hubs emulator; ETL notifications and bucket narratives use the Service Bus emulator. HTTP checkpoint routes remain isolated test facilities.
- `./dev` automatically mounts `.local/grf-demo-chelsea-united-v3/match.mp4` when present; `DEMO_VIDEO_PATH` can override it. Video remains optional and ignored.
- `./dev down`: stops only this Compose project, preserving database volumes.
- `python3 .github/scripts/render_architecture.py` and `python3 .github/scripts/render_development.py`: regenerate SVGs; visually inspect.

The recorded-match ETL and narrative stub are replaceable demo services, not production ETL or LLM implementations. Older backend fixtures remain isolated test doubles, not the viewer's runtime upstreams. Never execute generated code inside the API; the local agent workflow interprets goals using Microsoft Agent Framework and compiles a bounded rule DSL deterministically; fixture mode uses doubles. An arbitrary-code isolated executor is still to build. Stream Analytics belongs to the ETL service. Keep Azure cloud deployment separate; the Terraform foundation still needs networking, identities, actual service images and ASA configuration. Do not run cloud apply as part of local setup.

The Azure ETL pipeline and the narrative engine deploy to dev with their own Terraform (`etl/infra/`, `narrative-engine/infra/`); their commands are in each service's `docs/development.md` and `docs/deployment.md`. Confirm with the developer before any `terraform apply`, and stop the ETL's Stream Analytics job after testing (it bills while running).

Archived commands may use old paths. Recheck official hackathon rules in `legacy/research/` before submission. No CI or scheduled scraping is configured for the new layout.
