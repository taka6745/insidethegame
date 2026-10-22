# ReactCoach 11 — AI-Powered Adaptive Football Coaching

**Know your strengths. Read your opponent. Make the better move.**

Rust-powered, synthetic football matchup and tactical correction engine for Microsoft's **Inside the Game** hackathon.

> **Brand finalized:** ReactCoach 11. **GitHub repository:** `devgupta-9/reactcoach-11`. Microsoft Innovation Studio branding update was confirmed by the project owner.

## Core value

**Assess → Compare → Simulate → Counter-respond → Recommend → Explain.**

The user starts with an assessed player, a specific opponent and a football situation. ReactCoach 11 compares illustrative player attributes and the opponent's relative vulnerabilities, evaluates alternative actions from the same starting model and recommends a change. It reports a transparent **decision fit index**, **not** a predicted success percentage.

## Implemented initial scope

- Rust engine: synthetic player profiles, bounded 0–100 traits, explicit action/opponent trait weights, deterministic original-vs-recommended comparison.
- **Discrete opponent best-response:** each proposed move is challenged by two possible counters evaluated against the editable profiles; the strongest modeled counter reduces the final decision fit index. This is not a continuous physics simulation.
- Demo modes: open play, penalty, free kick.
- Rule-aware offside **position** check with a timing correction; not a complete offside offence or VAR decision.
- Axum REST API and synthetic match replay over SSE.
- Next.js interface for the decision lab and legacy synthetic match replay.
- Automated format/lint/test/build CI.

**Phase 2A:** a bounded deterministic spatial open-play simulator is available at
`POST /api/v1/simulations/open-play`. It compares an initial decision with tactical
adaptations under identical starting conditions and records movement and counter
evidence. See [the API contract](docs/SPATIAL_SIMULATION_CONTRACT.md) and
[verification report](docs/PHASE_2A_VERIFICATION.md).

**Not implemented:** real-player scouting data, continuous optimal opponent simulation, Microsoft Foundry model calls, realistic ball physics, calibrated outcome predictions or Azure deployment.

## Requirements

Rust stable (>=1.85), with rustfmt and Clippy, Node.js 22+, npm.
The committed dependency graph includes `hyper-util`, which requires Rust 1.85.

Run API:
```sh
cargo run -p reactcoach-api
```

Run frontend (new terminal):
```sh
cd apps/web
npm ci
npm run dev
```

Open http://localhost:3000.

On Windows, if Cargo is not on PATH, the local setup used for verification can
be invoked from the repository root with `powershell -NoProfile -File scripts/cargo.ps1 run -p reactcoach-api --locked`.
The wrapper uses the isolated toolchain under `%LOCALAPPDATA%\ReactCoach11\tools`
when present; it does not install tools or change the system PATH. A conventional
Rust installation on PATH takes precedence. The isolated GNU setup uses portable
LLVM MinGW for `dlltool` and Rust's bundled GCC runtime libraries.

The API reads shell environment variables (see `apps/api/.env.example`), not a
dotenv file. Next.js reads `apps/web/.env.local`. Its public API URL is embedded
at build time, so rebuild if it changes.

## Synthetic endpoints

```sh
curl http://localhost:8080/api/v1/health
curl 'http://localhost:8080/api/v1/decision-lab/demo?scenario=open_play'
curl 'http://localhost:8080/api/v1/decision-lab/demo?scenario=penalty'
curl 'http://localhost:8080/api/v1/decision-lab/demo?scenario=free_kick'
curl http://localhost:8080/api/v1/offside/demo
curl -N http://localhost:8080/api/v1/matches/demo/stream
```

## CI

```sh
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
cd apps/web && npm run lint && npm run typecheck && npm run build
```

Both dependency lockfiles are committed. CI installs with `npm ci` and uses
`--locked` for Rust checks.

Browser checks against the production frontend and local Rust API:

```sh
cd apps/web
npx playwright install chromium
npm run build
npm run test:e2e
```

Playwright starts missing local servers and checks desktop and mobile Chromium.
It reuses servers already running outside CI. Do not point these tests at production.
Screenshots and failure traces are written to ignored `apps/web/test-results/`.
See [Phase 1 verification and prioritized plan](docs/PHASE_1_VERIFICATION.md).

## Architecture / scope

- `crates/decision-engine`: matchup model, synthetic ratings, scenario comparisons and offside position.
- `crates/match-engine`: synthetic match replay.
- `crates/analytics`: deterministic match statistics.
- `crates/shared`: existing match event wire types.
- `crates/agents`: future roles (no deployed AI workflows).
- `apps/api`: Rust Axum / SSE.
- `apps/web`: Next.js decision lab and replay.
- [Product specification](docs/REACTCOACH_11_PRODUCT_SPEC.md)
- [Roadmap](docs/ROADMAP.md)

All demo player identities, ratings, movements and outcomes are **fictional**. No claim of a real professional athlete's strengths, weaknesses or reflexes, nor association with clubs, leagues or Microsoft, is implied. [MIT License](LICENSE).
