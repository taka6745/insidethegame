# Shift11 – AI-Powered Football Momentum Attribution

### Detect the shift. Attribute the player. Explain why the game changed.

## Overview

Shift11 is an AI-powered football analytics project designed to detect meaningful momentum shifts during a football match, identify the players who contributed to those shifts, reconstruct the supporting event sequences, and generate evidence-grounded tactical explanations.

Rather than simply displaying match statistics, Shift11 aims to answer:

- When did the game change?
- Which players contributed to the change?
- What sequence of events supported the shift?
- Why did the change matter tactically?
- What should the viewer watch next?

**Current development approach:** Build reliable, deterministic football analytics first, then use AI to explain verified analytical results.

## Core Principle

> Deterministic analytics establish what happened; AI explains why it mattered.

The analytical engine is responsible for calculating metrics, detecting shifts, and measuring player contributions. The AI layer will receive a structured fact pack containing verified results and supporting evidence.

AI-generated explanations must not invent match events, statistics, or player contributions.

## Proposed Architecture

```text
Synthetic Match Scenario
          |
          v
Formation-Aware Event Generator
          |
          v
Connected Possession Sequences
          |
          v
Event Validation
          |
          v
Match State and Spatial Metrics
          |
          v
Deterministic Momentum Analytics
          |
          v
Momentum Shift Detection
          |
          v
Player Contribution Analysis
          |
          v
Evidence Chain Reconstruction
          |
          v
Verified Analytical Fact Pack
          |
          v
Microsoft Agent Framework
          |
          v
Microsoft Foundry
          |
          v
Grounded Tactical Explanation
          |
          v
Interactive Match Dashboard
```

This architecture describes the intended system. Components will be marked as implemented only after they have been built and tested.

## Core Features

The planned application includes:

- Reproducible synthetic football match generation
- Formation-aware player roles and event selection
- Connected possession sequences
- Consistent pitch coordinates and attacking directions
- Deterministic momentum scoring on a 0–100 scale
- Five-minute rolling-window momentum analysis
- Momentum shift detection with persistence and cooldown rules
- Primary and secondary player contribution analysis
- Tactical player-role classification
- Supporting event-chain reconstruction
- Before-and-after match metrics
- Grounded AI tactical explanations
- Audience-aware explanations for fans, coaches, and analysts
- Interactive momentum timeline and shift drill-down
- Pitch-based event exploration

These features are planned capabilities, not a claim that every component is already implemented.

## Synthetic Match Data and Reliability

Shift11 initially uses synthetic match events so the system can be developed and tested without requiring proprietary player-tracking data.

Synthetic data must be clearly distinguished from real match data.

The generator will be developed to support:

- Multiple formations, including 4-3-3, 4-2-3-1, 4-4-2, and 3-5-2
- Player actions influenced by position and tactical role
- Connected passes, carries, recoveries, turnovers, and shots
- Plausible spatial progression and possession transitions
- Consistent pitch coordinates for both teams
- Appropriate attacking-direction changes between halves
- Reproducible output using a fixed random seed
- Controlled scenarios such as high pressing, counterattacks, defensive dominance, and harmless possession

A scenario will not automatically count as a momentum shift merely because it is labelled as one. The analytics engine must calculate the metrics and apply the predefined detection rules.

## Momentum Model

The initial design uses five components:

| Component | Initial weight |
|---|---:|
| Territory and field position | 20% |
| Possession value and progression | 25% |
| Pressure and recoveries | 20% |
| Chance creation | 25% |
| Possession control | 10% |

The proposed score ranges from 0 to 100 and uses a five-minute rolling window updated every 30 seconds, with greater weight assigned to more recent events.

These weights are initial design parameters. They must be tested and refined against controlled synthetic scenarios before being treated as reliable analytical settings.

### Momentum Shift Detection

The initial detection design requires all of the following:

- Momentum increases by at least 15 points.
- The change in relative momentum advantage is at least 10 points.
- The change persists for at least 60 seconds.
- At least three meaningful supporting events are present.
- Hysteresis and cooldown logic reduce duplicate or noisy shift markers.

These thresholds are proposed starting parameters and will be validated through testing.

## Player Attribution and Evidence

For each detected shift, Shift11 aims to identify:

1. The primary contributing player.
2. Secondary contributing players.
3. Their calculated contribution scores.
4. Relevant tactical roles.
5. A chronological evidence chain.
6. Before-and-after match metrics.

An illustrative attacking sequence is:

```text
Recovery
    |
    v
Progressive Carry
    |
    v
Line-Breaking Pass
    |
    v
Final-Third Entry
    |
    v
Shot
```

Possible analytical roles include:

- Momentum Catalyst
- Progression Driver
- Chance Creator
- Defensive Trigger
- Finisher

Player attribution must be calculated from verified event contributions. The generator must not randomly assign these labels.

Any displayed contribution percentage will represent the defined model's measured attribution, not proof of exact causal responsibility.

## Grounded Microsoft AI Layer

The intended Microsoft-first AI architecture includes:

- **Microsoft Agent Framework:** agent orchestration and application workflows.
- **Microsoft Foundry:** model access and AI application capabilities.
- **Azure:** hosting and supporting cloud services where appropriate.

The AI layer will receive a structured fact pack generated by the deterministic analytics engine.

Its responsibilities will be to:

- Explain verified momentum changes.
- Summarize the supporting event sequence.
- Describe the tactical significance of measured contributions.
- Adapt explanations to the selected audience.
- Reference the supporting evidence.

The AI layer will not independently calculate authoritative match metrics or invent events.

## Technology Stack

The planned technology stack includes:

- Python
- JSON
- Git and GitHub
- Pandas or NumPy where useful
- Microsoft Agent Framework
- Microsoft Foundry
- Azure services where appropriate

Dependencies will be introduced when needed rather than added without a clear purpose.

## Development Roadmap

### Phase 1 — Project Foundation

Establish the repository, project structure, initial data models, development environment, and documentation.

### Phase 2 — Realistic Synthetic Match Generator

Build connected possession sequences, formation-aware player actions, spatially consistent events, reproducible generation, and controlled match scenarios.

### Phase 3 — Data Validation and Automated Testing

Validate event schemas, team-player relationships, chronology, possession continuity, coordinates, reproducibility, and scenario behaviour.

### Phase 4 — Momentum Analytics and Shift Detection

Implement the five-component momentum model, rolling windows, shift thresholds, persistence checks, and cooldown logic.

### Phase 5 — Player Attribution and Tactical Evidence

Calculate player contributions from verified events, classify analytical roles, and reconstruct supporting event chains.

### Phase 6 — Microsoft AI and Personalized Explanations

Integrate Microsoft Agent Framework and Microsoft Foundry to explain verified results for different audiences.

### Phase 7 — Interactive Dashboard and Match Exploration

Display the match timeline, momentum graph, shift markers, player contributions, pitch events, and evidence behind selected shifts.

### Phase 8 — Integration, Deployment, and Documentation

Connect the components into a working application, document the architecture and setup, configure required credentials, and deploy to Azure if appropriate for the final solution.

### Phase 9 — Final Verification and Submission

Run end-to-end tests, verify scenario behaviour, fix defects, prepare the demonstration, and complete the hackathon submission requirements.

## Development Status

**Current status: Foundation established; synthetic data pipeline under development.**

The initial Python data models and a first version of the synthetic event generator have been created. The generator still requires improvements to possession continuity, spatial realism, role-aware actions, and scenario generation.

The momentum engine, player attribution, AI explanation layer, and interactive dashboard remain planned until their implementations and tests are completed.

Project progress will be updated as individual components are implemented and verified.

## Development Philosophy

Shift11 separates analytical computation from narrative explanation.

The project prioritizes:

- Reproducibility
- Transparent calculations
- Validated synthetic data
- Evidence-backed player attribution
- Clear separation between measured results and AI-generated explanations
- Honest reporting of implementation status

## Project Documentation

The `docs/` directory contains:

- `Phase_Wise_Development_Plan.pdf`
- `Project_Theory_and_System_Design.pdf`
- `Microsoft_First_Learning_Resources.pdf`

These documents will be kept aligned with the actual implementation.

## Project Structure

```text
Shift11/
├── data/       # Generated synthetic match data
├── docs/       # Project documentation
├── src/        # Application source code
├── tests/      # Automated tests
├── .gitignore
├── .gitattributes
└── README.md
```

Additional source and test modules will be added as development progresses.

---

**Shift11 is under active development.** Its goal is to make football momentum analysis more interpretable by connecting measurable changes in team performance to the players and event sequences that support them.
