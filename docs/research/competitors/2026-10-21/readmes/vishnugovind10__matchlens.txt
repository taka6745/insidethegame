# MatchLens

**AI Match Intelligence & What-If Simulation.** Turn synthetic football events into explainable match intelligence: what changed, what evidence supports it, why it matters, and what a conditional scenario would look like if the pattern continues.

Built as a demo concept for the Microsoft + Premier League “Inside the Game: Developer Hackathon.” MatchLens uses synthetic football event data for the hackathon prototype and does not represent official Premier League match data.

## Demo flow

```text
Synthetic events → replay → match metrics → shift detector → immutable EvidenceObject
                                                        ├─ grounded explanation
                                                        └─ What-If Engine → WhatIfResult
```

The event stream is authoritative. The backend computes all metrics and creates observed evidence; the browser renders SSE values without recalculating them. What-If results are separately materialized and include their own observed t0 anchor, assumptions, and limitations. No goals or scores are projected.

## Hackathon context

The demo turns synthetic football events into real-time match-state changes, traceable evidence, and a bounded explanation suited to broadcast/studio discussion or a streaming second-screen experience. The narrative in this MVP is a deterministic local fallback; an external generative AI provider and official live match feeds are not implemented.

The technical flow is `Synthetic Events → Replay Engine → Match State Engine → Detector → EvidenceObject → Narrative → WhatIfEngine → React UI`.

## Run locally

Requirements: Python 3.11+, Node.js 20+.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e '.[test]'
uvicorn app.main:app --reload
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. API docs are at <http://localhost:8000/docs>; health at <http://localhost:8000/health>.

## Container

```sh
docker compose up --build
```

Frontend: `http://localhost:5173`; API: `http://localhost:8000`. The backend image runs on port 8000 and is suitable for an Azure Container Apps container deployment. Local mode needs no credentials.

## Verification

```sh
python scripts/run_golden_demo.py
cd backend && python -m pytest
cd ../frontend && npm run typecheck && npm run build
```

GitHub Actions runs backend tests, frontend type checking, and the production frontend build.

## Data, metrics, and boundaries

The fixture `backend/data/synthetic_events.jsonl` is a deterministic, fictional Arsenal vs Liverpool sequence with baseline and sustained high-press phases. The five UI metrics use canonical names: `pressing_intensity`, `high_recoveries_rate_10min`, `forced_turnovers_rate_10min`, `territory_share`, and `attacking_threat`. The formulas are simplified demo measures, defined in [the data model](docs/data-model.md).

`EvidenceObject` is a frozen Pydantic model constructed by the deterministic backend engine and exposed through `/observed/latest` and `/observed/{evidence_id}`. `WhatIfResult` is a separate frozen model, generated from scenario inputs via `POST /what-if`; its UI only consumes that response and the opaque evidence ID. The local narrative is deterministic and grounded in evidence fields. No generative provider is enabled in this demo build; `.env.example` reserves Azure configuration names for a future provider adapter.

See [architecture](docs/architecture.md), [API contract](docs/api-contract.md), [demo script](docs/demo-script.md), [data model](docs/data-model.md), and [Azure notes](docs/microsoft-azure.md).

## Limitations

This is a deterministic synthetic demonstration, not an official feed, causal model, forecasting product, or production deployment. Scenario outputs are conditional projections only. Event generation, simplified metric definitions, detector thresholds, and provider integration need domain review before any real match use.

## License

MIT. See [LICENSE](LICENSE).
