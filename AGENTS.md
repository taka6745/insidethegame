# Working in InsideTheGame

A hackathon application: a simulated match feed, an Azure ETL pipeline (`etl/`), a narrative engine (`narrative-engine/`), a user backend, a frontend, the local stack and demo control (`local/`), Terraform (`terraform/`) and the edge proxy (`edge-proxy/`). Everything is implemented and deployed with `./dev azure up` (status: [README](README.md#status)). Read each service's README before changing it.

- Keep code small, readable and reusable. Add implementation only when requested.
- Preserve local changes. Keep credentials in ignored files or approved secrets; never print or commit them.
- Distinguish planned, implemented, tested and deployed work. Deployed status lives only in the root README's Status section and `terraform/README.md`.
- Never name the local development LLM provider, its hosts or model families in files. Azure AI Foundry and Azure model names are welcome.
- The detailed sections of `docs/design/plan.excalidraw`, plus later decisions in the READMEs, define the plan. Code and tests never cite plan sections or review tags.
- Preserve the original example prompts in `narrative-engine/docs/design/example-prompts/`; runtime prompts get a new versioned file.
- The user backend owns audience definitions and exposes a read-only configuration API. The narrative engine reads those definitions and owns bucket framing. The user backend receives already-bucketed narratives and routes them without rewriting.
- User questions never trigger the shared narrative workflow. Narrative history uses the narrative service's GraphQL API; live narratives use Service Bus.
- Live match events reach the user backend through its own Event Hubs consumer group, for every match. History and computed stats use ETL GraphQL.
- ETL owns standard stat calculations; event history, stats and the stat catalogue live in its Azure SQL. The backend accesses them through ETL GraphQL, never direct DB connections. Reuse existing stats before generating custom calculations; ordinary cards must not fetch raw history or recalculate standard stats.
- User-specific code/calculations belong to `user-backend/` (bounded rule DSL; an isolated executor is not built), not ETL.
- Test changed behaviour and inspect actual outputs. Design diagrams are not tested infrastructure.
- Label synthetic data and preserve provenance/licences.
- Preserve ignored `.local/` runtime environments and assets; do not upload them.

## Docs

Thirteen tracked `.md` files, no more: the root `README.md` (judge-facing, with the Status section), `AGENTS.md`, `docs/submission.md`, one `README.md` per service (user-backend, narrative-engine, etl, frontend, data-generation, local, terraform, edge-proxy) holding what it is, a diagram, how to run and test it, its contracts and one-line decisions, plus the files code loads at runtime (`user-backend/backend/agents/skills/event-data/SKILL.md`, `frontend/assets/league/PROVENANCE.md`). The cross-service contracts live in `local/README.md` (cite them as "local/README.md Contracts §N"). No plan logs, design history, component pages, duplicated overviews or research notes; READMEs stay short and graphical (tables, the rendered `architecture.svg`), under 300 lines.

## Code organisation

Each service uses the same folders where they apply: `contracts/` (JSON schemas), `infra/` (Terraform), `tests/`, one folder per component; developer-only code in `devtools/`.

```text
HTTP / UI view → application service → domain model / pure engine
                         ↓
                repository or adapter → database / external API
```

| Layer | Owns | Must not do |
| --- | --- | --- |
| `models/` | Typed inputs, rules, events and invariants | Open databases or call models/APIs |
| `services/` | Use cases, orchestration, state transitions | Depend on vendor JSON keys or HTTP route objects |
| `repositories/` | SQL, persistence and transactions | Decide UI behaviour or interpret user requests |
| `adapters/` | Translate external events, model APIs and replay sources | Leak provider-specific fields into the rule engine |
| `routes/` / frontend views | Validate/translate requests, render responses | Open DB connections or implement calculations |
| `agents/` | Define semantic goals; compile bounded rules; validate/repair | Execute arbitrary model output or bypass typed contracts |

- One responsibility per file; split when reasons to change differ. No catch-all helpers or duplicated business rules.
- Use Microsoft Agent Framework for agent orchestration; compile bounded goals deterministically; tests and benchmarks substitute agent doubles inside the same workflow.
- Inject dependencies in one composition root. Runtime code has no fixture mode and never reads recordings; doubles live under `tests/` or `benchmarks/`.
- Validate at boundaries: strict typed models; LLM output is untrusted data; never `eval`/`exec` a structured filter.
- Repositories own transactions; never report a mutation before commit.
- Test observable behaviour against real Postgres and the running API/UI; keep expensive benchmarks opt-in.
- Model configuration stays local: generic variable names, an example file, URLs and keys in ignored files. With no model configured the service reports not ready and refuses model work; it never falls back to a double. Never commit request logs or provider dumps.
- All browser and Node code is TypeScript; plain `.js` exists only as a generated build artifact.

## Tooling

- `./dev doctor`, `./dev up [azure|backend]`, `./dev test [azure|backend]`, `./dev down`: the local stack ([local/README.md](local/README.md)). Only set `ACCEPT_EULA=Y` with the developer's consent.
- `./dev demo start [fixture…]` / `./dev demo purge`: purge every owner (feed → ETL → engine → backend), then start one feed run per fixture at the next whole minute. Configuration stays.
- Judge demo: the viewer's **Start demo** / **Cancel demo** call demo control (`local/demo_control.py serve`, public `/demo-api/`): always three fixtures, main game first. Seeds: `docker compose -p itg-local exec demo-control python /checks/demo_control.py record {point} [--from {point}]`, then `capture {point}` ([demo control](local/README.md#demo-control)). Seed routes exist only with `DEMO_SEEDS=1`; core services never branch on a demo; `./dev azure up --release` leaves it off.
- `./dev terraform check`: validation and mock-provider tests in Docker. `./dev azure up|down|status|plan [--release]` deploys every service ([terraform/README.md](terraform/README.md)). Confirm with the developer before any `terraform apply`; stop Stream Analytics after testing (it bills while running); do not run cloud apply as part of local setup. The spend guard (`terraform/guard`) is applied first and kept by `down`.
- `./dev benchmark replay`: replay golden set against the local model.
- `python3 .github/scripts/render_architecture.py`, `render_development.py`, `render_master_plan.py`: regenerate the diagrams and inspect them.
- The edge proxy (`edge-proxy/`, `npx wrangler@4.151.3 deploy`) points `msft-hackathon.koda-software.com` at the frontend; `./dev azure up` rewrites its `UPSTREAM`.

Recheck the official hackathon rules before submission. `.github/workflows/ci.yml` runs every service's tests (no cloud or model calls).
