# Match Storyteller

**An explainable, AI-assisted storyteller for a fictional football match.**

Match Storyteller is a local-first project for Microsoft's [Inside the Game: Developer Hackathon](https://events.microsoft.com/flow/microsoft/plmshackathon/registration/page/landing). It will replay original, synthetic football events, calculate match statistics from those events, and explain selected moments in two styles: **Fan** and **Analyst**. Every insight is designed to show the evidence behind it.

> **Status: planning / pre-implementation.** This repository currently contains the [product requirements and build contract](PRD.md) and project-local agent skills. The application, setup commands, runnable demo, and video have **not** been built yet. The features below describe the intended MVP, not existing functionality.

## The idea

A match event feed tells you *what* happened. Match Storyteller aims to show *why a moment matters* without making up facts:

```text
Synthetic match events
        ↓
Deterministic score, statistics, and key-moment selection
        ↓
Evidence packet with source event IDs
        ↓
AI-generated explanation for a Fan or Analyst
        ↓
Replay timeline and grounded insight card
```

The replay will be accelerated and simulated—not a live football data feed. Teams, players, events, and visuals will be fictional. The project will not use real match footage, official club branding, or scraped match data.

### Planned MVP

- Play, pause, step through, and reset a synthetic 90-minute match in a single-page web UI.
- Track score, shots, shots on target, passes, tackles, and current possession from an ordered event stream.
- Identify a small number of meaningful moments, such as goals and saved shots.
- Explain those moments in accessible **Fan** language or evidence-focused **Analyst** language, with an optional favorite-team perspective.
- Display the event-derived evidence used for each insight. Keep the replay functional when AI inference is unavailable, and show narration failures explicitly.

The detailed event schema, UI/API contracts, acceptance tests, time budget, and exclusions are in **[PRD.md](PRD.md)**. It is the source of truth if a feature description here is less precise.

## Planned technology

| Area | Planned choice |
|---|---|
| Application | Python 3.12, FastAPI, Pydantic, Jinja2, vanilla JavaScript/CSS |
| Match data and statistics | Seeded synthetic fixture and deterministic Python reducer |
| Narrator | A single Microsoft Agent Framework agent, **subject to the compatibility check in the PRD** |
| Inference | Server-side, OpenAI-compatible chat completions through the maintainer's existing LiteLLM proxy |
| Development | Copilot CLI or Codex CLI; neither is a runtime inference dependency |
| Delivery | Local test build; no Azure account, credits, or deployment assumed |

The first implementation step is a time-boxed test of Agent Framework with the configured proxy/model. If that integration does not work, the maintainer will choose and document a fallback rather than claiming Microsoft runtime integration that is not present.

## Running and evaluating

**Not available yet.** There is no `app/`, `pyproject.toml`, or `.env.example` in this repository at this stage, so installation or run commands would be misleading. Once the MVP is implemented, this section will contain verified Python 3.12/`uv` installation, local launch, tests, and judge-facing test-build instructions.

The planned test build will support a clearly labeled **replay-only mode** without a proxy key. Live AI narration will require a server-side model endpoint, model name, and API key. Never put those values in browser code or a public issue; the future `.env.example` will contain placeholders only. The application will limit uncached inference calls per server process, but that is **not** a substitute for an upstream spending cap.

## Project roadmap

1. Confirm Agent Framework + LiteLLM chat-completions compatibility with a single low-cost request.
2. Build and test the seeded fixture, deterministic statistics, key moments, and evidence packets.
3. Add validated, cost-limited Fan/Analyst narration and a responsive replay UI.
4. Publish verified run/test instructions, a public code repository, and a demonstration video under two minutes.

Target effort is **10–15 focused hours**. Progress and acceptance criteria follow the staged delivery plan in [PRD.md](PRD.md#12-delivery-sequence-and-time-budget).

## Working with coding agents

This repo includes project-local skills from [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) in `.agents/skills/`, discoverable by Copilot CLI and Codex CLI. Shared checklists and attribution are in `.agents/references/` and [.agents/UPSTREAM.md](.agents/UPSTREAM.md). [AGENTS.md](AGENTS.md) instructs coding agents to follow the PRD over generic skill advice. The skills help build the app; they do not provide match data, an AI model, or Azure credits.

## Hackathon and licensing notes

The [official hackathon rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md) require an original project built with synthetic, football-realistic data, a public GitHub code repository, a public demo video shorter than two minutes, and a functioning demo or test build accessible to judges during the judging period. Check the registration portal for current requirements before submitting. This project is independent and is **not** an official Premier League or Microsoft application.

The upstream skill pack has its own license at [.agents/LICENSE](.agents/LICENSE). **No license has been selected yet for the original Match Storyteller project**; the skill-pack license does not apply automatically to future application code.
