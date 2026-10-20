# Working in InsideTheGame

This is a hackathon application in build: `etl/` and `narrative-engine/` are implemented and deployed to dev; the other services are at design stage. Active areas: `data-generation/`, `etl/`, `narrative-engine/`, `user-backend/`, `frontend/`. Read each service's README before changing it.

- Keep code small, readable and reusable. Add implementation only when requested.
- Preserve local changes. Keep credentials in ignored files or approved secrets; never print or commit them.
- Keep READMEs short and graphical. Distinguish planned, implemented, tested and deployed work.
- The detailed sections of `legacy/design/plan.excalidraw`, plus later decisions in active docs, define the plan. Older sketches are historical.
- Preserve original example prompts in `narrative-engine/docs/design/example-prompts/`. Resolve their output contracts before implementation.
- User questions never trigger the shared narrative workflow. Narrative history uses the narrative service's GraphQL API; live narratives use Service Bus.
- Live match events reach the user backend through one shared Event Hubs consumer for the demo match. History and computed stats use ETL GraphQL.
- User-specific code/calculations belong to `user-backend/`, with an isolated generated-code executor, not ETL.
- Test changed behaviour and inspect actual outputs. Design diagrams are not tested infrastructure.
- Label synthetic data and preserve provenance/licences. Do not execute archived competitor code.
- `legacy/` preserves research, scraping scripts, simulator code, earlier docs and outputs. It is inactive; do not revive its automation or overwrite it during application work.
- Preserve ignored `.local/` runtime environments and assets; do not upload them.

## Service layout and docs

Each implemented service uses the same top-level folders where they apply: `contracts/` (what consumers can rely on), `infra/` (Terraform), `tests/`, `docs/`, plus one folder per component whose name says what it holds. Developer-only code goes in `devtools/`.

Each service's `docs/` has the same pages: `README.md` (index tree), `overview.md`, `architecture.md`, `components/<one page per code folder>.md`, `development.md`, `deployment.md`, `decisions.md`, and `design/` for original design material that is no longer updated. Every page opens with an **In short** summary and a facts table; every numbered section opens with a one-line *In short*. See `etl/docs/` and `narrative-engine/docs/`.

## Current tooling

Render the six SVG diagrams with `python3 .github/scripts/render_architecture.py`; visually inspect the results. Service test, run and deployment commands are in each service's README and `docs/development.md` / `docs/deployment.md`.

Archived commands may use old paths. Recheck official hackathon rules in `legacy/research/` before submission. No CI or scheduled scraping is configured for the new layout.
