# MatchSight AI: Hidden Match Reconstruction & Tactical Intelligence

Football is a sequence of changing states, tactical decisions, consequences and turning points. This engine reconstructs that story from synthetic tracking and event data and explains **what happened → what changed → what it caused → why it mattered**.

**INGEST → INTERPRET → EXPLAIN → RENDER → PERSONALIZE**

## Run

```bash
./run.sh          # API on :8000 (builds intelligence in ~17s on startup), UI on :3000

Open http://localhost:3000. The UI has three views:
- **Lobby (`/`):** a live match (a recorded real DFL match replayed in real time: `LIVE_MATCH=dfl-J03WOY` by default, starting `LIVE_STARTED_MIN=20` minutes in) and past matches (every `data/dfl_*_h1/h2.json`, `data/cv_*.json` and the synthetic test match).
- **Match page (`/match/<id>`):** whole-match highlights with a Watch link for each, team stats, shapes per half, tactical chapters, top players, cards and substitutions.
- **Studio (`/match/<id>/studio?part=h1`):** the pitch replay and analysis for one half. `&moment=<id>` opens a highlight directly.

API: `GET /matches` (lobby) and `GET /matches/{id}` (whole-match summary). Every `/match/...` endpoint takes `?match=<id>&part=<h1|h2|clip|full>`.
.venv/bin/python -m pytest -q tests   # ground-truth regression
```

## Demo path

1. Press **Play** (8x) and watch the live tactical state and latest insight update.
2. In **Match Story**, click **SHAPE 66'**. The clock jumps back, the build-up replays at 1x with the key players and team shape highlighted, and the panel shows the evidence chain.
3. Scroll to **What if?** to compare the actual match with a re-simulation that leaves out that tactical decision.
4. Switch to **Fan mode** (same insight, broadcast language) and **Player mode** (click Nkemelu #17 on the pitch).
5. Open the **Machine-readable insight** JSON (overlay payload). The same payload is also served at `/match/moments/{id}/overlay`.

## Scripted ground truth (seed 7)

| Min | Script | Detected as |
|---|---|---|
| 15–30 | Ashford high press | `TACTICAL_TURNING_POINT` 16' → goal 24', press bypass 21' |
| 30–45 | Belmont low block + counters | `TACTICAL_TURNING_POINT` 31' → counter goal 38' |
| 61 | Substitution (Nkemelu) | `SUBSTITUTION_IMPACT`, followed by the shape change (linked as "preceded", not causal) |
| 65 | 4-3-3 → 4-2-3-1, right-side press | `FORMATION_SHIFT` 66' (formation detected from positions) → goal 70' |
| 76 | Belmont red card | `RED_CARD_IMPACT` → goal 86' |

## Observed vs inferred: hidden-player reconstruction

A broadcast camera never shows all 22 players. The synthetic match is served **as a camera would see it**:
`backend/reconstruction/observation.py` hides players (seeded), and `estimator.py` reconstructs them. All analytics then run on the reconstructed state; the simulator's ground truth is used only for evaluation and the "Truth" / "Error" overlays.

- **Team-level estimate:** fit the team block (centre and scale) to visible players using role anchors that adapt online. A hidden player = last seen position + team block shift, blending towards his role slot. Keepers use a keeper model.
- **Live mode** uses only past observations; a test checks that changing the future never changes a live estimate. **Replay mode** (VOD) also runs backwards from the next sighting, fuses both by inverse variance and enforces reachability. Replay results are labelled retrospective.
- **Every position is labelled** `observed | inferred`, with confidence = P(error ≤ 5 m), a calibrated 80% uncertainty radius and the evidence used (`previous_position`, `team_shape`, `ball_position`, `player_role`, `future_reappearance`). Calibration is fitted on a different match (seed 11).
- **Abstention:** if a team averages fewer than 2.5 observed outfield players in a minute, its tactical state becomes `INSUFFICIENT_VISIBILITY`.
- **Moments** carry `coverage`, confidence scaled by visibility, and a visibility note. Each evidence item is tagged as observed events or inferred positions.

```bash
.venv/bin/python -m backend.reconstruction.evaluate     # calibrate on seed 11, evaluate on seed 7 -> data/eval/report.json (~70 s)
VIEW=vod ./run.sh                                       # analyse the camera estimate instead of ground truth (default: truth)
```
API: `/evaluation`, `/match/frames?mode=replay|live|truth`, `/match/players/states?t=&mode=`, and `/match/state` (coverage and per-player states).

**Hidden-player position error** (seed 7, measured):

| Visibility | Observed per second | Freeze at last sighting | Live | Replay | Replay ≤5 m / ≤10 m | Inside reported radius (target 80%) |
|---|---|---|---|---|---|---|
| k=18 | 18.0 | 5.44 | 3.5 | **3.03** | 84% / 100% | 83% |
| k=14 | 14.0 | 6.85 | 3.99 | **3.38** | 80% / 99% | 80% |
| k=10 | 10.0 | 7.82 | 4.86 | **3.89** | 73% / 97% | 83% |
| k=6 | 6.0 | 8.84 | 7.01 | **5.33** | 59% / 90% | 78% |
| broadcast | 14.2 | 5.97 | 5.01 | **3.77** | 75% / 95% | 84% |

**Tactical detection F1 vs simulator labels:**

| State used | HIGH_PRESS (team-minutes) | TACTICAL_SHIFT (+-3 min) | COUNTERATTACK (+-5 s) | ATTACKING_TRANSITION (+-3 s) | DEFENSIVE_TRANSITION (+-3 s) |
|---|---|---|---|---|---|
| Full ground truth | 0.738 | 0.8 | 0.353 | 0.739 | 0.746 |
| broadcast · observed only | 0.727 | 0.727 | 0.353 | 0.666 | 0.66 |
| broadcast · reconstructed replay | 0.738 | 0.8 | 0.353 | 0.719 | 0.73 |
| k=6 · observed only | 0.0 | 0.5 | 0.353 | 0.714 | 0.703 |
| k=6 · reconstructed replay | 0.706 | 0.8 | 0.353 | 0.681 | 0.682 |

Counterattacks are detected from the ball and events, which are always observed, so visibility does not affect them. Their F1 is limited by the detector also flagging fast breaks that the simulator never scripted as counters.

**Current model and evaluation (13 Oct 2026):** [docs/reconstruction_evaluation.md](docs/reconstruction_evaluation.md) and [model card](docs/reconstruction_model_card.md). The production model `r13_mlp_aug_ens3` was evaluated on DFL 7-fold held out (live 8.10 m / replay 6.66 m vs 14.28 / 10.54 m for the formation estimator), on real-broadcast SoccerNet-GSR re-entries (live 6.74 m) and on SkillCorner A-League re-entries (live 7.70 m). Analysis of 30 reconstructed matches: [docs/match_analysis_report.md](docs/match_analysis_report.md). Earlier results: Real-football results, dataset choice and the trained model: [docs/HIDDEN_STATE_RECONSTRUCTION.md](docs/HIDDEN_STATE_RECONSTRUCTION.md). On unseen Bundesliga teams, with real broadcast-camera masking, the learned model reaches 8.2–8.3 m (live) and 7.0 m (replay) against 13.8–13.9 / 10.0–10.4 m for the formation estimator and 15.5–16.0 m for last position.

## Layout

```text
simulator/           deterministic scripted match (scenarios.py = ground truth + counterfactual flags)
backend/
  models/            MatchData (ingest contract), Pydantic schemas
  analytics/         movement, possession, passing, shape + formation detection
  tactics/           tactical_state (minute timeline, press index), high_press, counterattack, shift
  moments/           detector (evidence chains), story (causal graph, chapters)
  narratives/        NarrativeGenerator (deterministic; Foundry seam)
  counterfactual/    what-if via controlled re-simulation
  api/main.py        FastAPI: /match, /match/state, /match/events, /match/moments, /match/players, /match/story, /match/stream (SSE)
frontend/            Next.js studio UI (pitch, intelligence panel, match story)
docs/COMPUTER_VISION_PLAN.md
```

## Azure readiness

- **Microsoft Foundry:** implement `FoundryNarrativeGenerator.generate` and set `NARRATIVE_BACKEND=foundry`. Its input is moment JSON with evidence only, so the model has no numbers to invent.
- **Azure Event Hubs:** produce the `{meta, players, events, frames}` contract. `/match/stream` (SSE) is the placeholder for the live feed.
- **Azure Container Apps:** the API is stateless, and the intelligence is rebuilt from a seed or source on startup.
- **Azure Storage / Fabric:** persist raw frames, events and moment JSON for history and BI.
