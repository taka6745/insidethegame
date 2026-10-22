# VYBE — Every Fan Belongs

**One synthetic football match. Three ways to experience it.**

VYBE turns a **fictional football match** into three accessible, personalized fan experiences: **Young Fan**, **Accessible Fan**, and **Analyst Fan**. Match facts are deterministic; evidence-constrained Azure AI narration and model-directed tool selection are implemented in code. **Live Microsoft Foundry integration is required for submission, but not yet verified or deployed.**

**[Watch the 53-second demo](https://youtu.be/c717qul116M)** · **[Judges' 3–5 minute testing guide](docs/JUDGES_TESTING_GUIDE.md)** · **Live demo: pending Azure deployment and verification**

> **Synthetic data only:** Aurora FC, Harbor United, players and events are fictional. No official Premier League feed or real-time match coverage. Browser speech is not AI translation.

### Quick tour

1. **Young Fan:** goals, celebrations, glossary and quiz.
2. **Accessible Fan:** English/Arabic/Czech captions, larger text, contrast, keyboard and step-by-step playback.
3. **Analyst Fan:** recorded match statistics, 15-minute weighted event activity and timeline filters.

### Deployment preparation

- [Mandatory Foundry launch and live proof gates](docs/FOUNDRY_REQUIRED_LAUNCH.md)
- [Updated delivery milestones](docs/DELIVERY_PLAN.md)
- [Final demo storyboard and evidence checklist](docs/FINAL_DEMO_STORYBOARD.md)

- [Azure cost and security preflight](docs/AZURE_DEPLOYMENT_PREFLIGHT.md)
- [Azure launch runbook](docs/AZURE_LAUNCH_RUNBOOK.md)
- [Validation evidence and limitations](docs/FINAL_ACCEPTANCE_CHECKLIST.md)

## Experiences

| Persona | Features |
| --- | --- |
| **Young Fan** | Goal celebration, plain-language football glossary, interactive goal quiz, approachable match commentary |
| **Accessible** | Optional browser spoken commentary, adjustable voice speed, high-contrast mode, larger text, keyboard replay shortcuts, optional descriptions of shots and passes, screen-reader-friendly step-by-step event navigation |
| **Analyst** | Recorded shots/passes, highlights/goals/all-events timeline filters, first-vs-second-half comparison, event-based momentum indicator, goal turning points and evidence-backed narratives |

**Interpreting analytics:** Momentum is a custom weighted event-activity score (goal = 3, shot = 2, completed pass = 1) in 15-minute windows. It is **not** possession, expected goals (xG), or a professional tactical model. Half comparisons use recorded synthetic events only; missing events must not be interpreted as real-world zero activity.

## Architecture

- **Frontend:** React, TypeScript, Vite, CSS; browser SpeechSynthesis API for optional spoken commentary.
- **Backend:** Python FastAPI; deterministic replay engine that calculates score, passes and shots from ordered synthetic events.
- **Narration:** Evidence-based, persona-specific commentary; Foundry-required Azure AI selection and ordering of exact, server-verified fact segments with allowlisted framing and deterministic fallback.
- **Data:** Local synthetic match fixture. No external sports API required.

The Vite development server proxies `/v1` and `/health` to the FastAPI service on port **8000**. Playback requests all validated replay snapshots once via `/v1/matches/replay/states` and then scrubs locally; `/v1/matches/replay` remains available for individual queries.

## Architecture diagram

This diagram shows the **current local prototype**. The target architecture requires a live Microsoft Foundry-hosted model, but the endpoint is **not yet deployed or validated**.

```mermaid
flowchart TD
    FAN["Fan in browser"] --> WEB["React / TypeScript / Vite\nYoung · Accessible · Analyst"]
    WEB -->|"HTTP /v1"| API["FastAPI backend"]
    WEB --> SPEECH["Optional browser speech synthesis"]
    WEB --> PREFS["Browser localStorage preferences"]
    API --> ENGINE["Deterministic replay engine"]
    ENGINE --> EVENTS["Synthetic match events"]
    API --> NARR["Event-grounded narration"]
    NARR --> FALLBACK["Deterministic fallback"]
    NARR -. "Required for final live demo; pending verification" .-> AZURE["Microsoft Foundry-hosted Azure OpenAI model"]
    API -. "Bounded read-only tool selection" .-> AZURE
```

**Data boundaries:** No official or live Premier League feeds are used. Match statistics derive from fictional events; browser speech uses installed OS/browser voices. The existing Azure model adapter is not evidence of a deployed service or managed Foundry Agent Service. Azure deployment topology will be documented after live validation.

## Run locally (Windows PowerShell)

Use two terminals from the repository root.

**Terminal 1 — API**

```powershell
cd apps/api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m uvicorn vybe.main:app --reload --port 8000
```

**Terminal 2 — frontend**

```powershell
cd apps/web
npm.cmd install
npm.cmd run dev
```

Open **http://localhost:5173** (or the port Vite prints if 5173 is occupied).

## Validation (automated and manual checks)

```powershell
cd apps/web
npm.cmd run build
```

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m pytest tests -q
```

**Windows PowerShell vs Command Prompt (CMD):** PowerShell may block the `npm.ps1` or `npx.ps1` script with an execution-policy error. Use the `.cmd` launchers instead; no execution-policy change or administrator access is needed. In **CMD**, **Git Bash**, and **Linux/macOS** shells, use the normal `npm` and `npx` commands (on Git Bash, `.cmd` is generally unnecessary). The commands below assume you are inside `apps/web`:

```powershell
# Windows PowerShell
npm.cmd ci
npm.cmd run dev
npm.cmd run build
npx.cmd playwright test
```

```sh
# Windows CMD, Git Bash, Linux or macOS
npm ci
npm run dev
npm run build
npx playwright test
```

Playwright browser setup (first time): `npx.cmd playwright install chromium` in PowerShell, or `npx playwright install chromium` in other shells. The Playwright configuration starts the Vite dev server automatically during tests. Browser speech is mocked in the automated full-time test; audible speech still requires manual browser/OS verification.

**Validation:** CI runs backend tests, browser tests, builds and dependency checks; consult GitHub Actions for current results. Earlier manual acceptance checks recorded 24/24 passes; these are historical, not a substitute for deployment smoke tests. Current PR checks must be reviewed separately. Azure deployment, full WCAG audit and comprehensive security certification remain unverified. See the [full validation history and scope](docs/FINAL_ACCEPTANCE_CHECKLIST.md).

## New fan experiences

- **Multilingual commentary:** English, Arabic and Czech event captions, summaries and browser speech narration in Accessible mode. These are deterministic translations of synthetic events, **not Azure AI translations**. Browser voices for Arabic and Czech may not be installed.
- **Live captions:** optional text for the current match event, updated as playback progresses. Captions are event-synchronized rather than word-by-word speech transcription.
- **Match story recap:** evolving event-grounded score and goal narrative for all personas.
- **Timeline views:** Highlights, Goals-only, and All events; the Goals view shows goal events without changing the underlying match statistics.
- **Interactive match insights:** select a 15-minute Analyst momentum bucket to filter timeline events; select again or clear to reset.
- **Fan preferences:** language, persona, high contrast, large text, captions, timeline display, expanded narration and voice speed saved in the current browser using localStorage when permitted; the app continues without persistence when storage is blocked. No account or cloud sync.
- **Guided demo:** short automated tour of Young, Accessible and Analyst using selected synthetic events; no Azure resources needed.

## Accessible controls

In Accessible mode, enable **Step-by-step playback (screen reader friendly)** to pause automatic event progression and move between events with **Previous event** and **Next event**. This allows an external screen reader to finish reading captions before the next event; the app cannot detect when Narrator finishes speaking. The setting persists in the current browser.

In Accessible mode, **Tab** navigates controls. When focus is not inside an interactive control, **Space** toggles playback and **Left/Right arrows** step through events. Spoken commentary is optional and depends on the installed browser and operating-system voices. Voice-speed changes apply to the next utterance, not the current one.

## Azure readiness

The prototype can run locally without paid Azure resources. **Live Microsoft Foundry integration is mandatory for the final hackathon demo**; deterministic fallback is for resilience, not a substitute. Cloud provisioning, credentials, costs, deployment and live service validation must be performed separately. Never commit secrets or Azure API keys. The UI distinguishes deterministic narration from Azure-assisted selection and ordering of verbatim verified fact segments when the backend reports that mode; do not interpret this as proof that a live Azure deployment is currently active.

## Limitations and responsible use

- Not real football match data, real-time video or an official Premier League product.
- AI-generated or AI-assisted descriptions are experimental; the deterministic event engine is the source of truth for match scores.
- Browser speech voices vary, and expanded narration needs manual timing/accessibility validation.
- Goal-based turning points are illustrative, not causal tactical analysis.
- This is a hackathon prototype; production readiness, WCAG compliance, security review and Azure integration are **not** yet certified.

## Project layout

- `apps/api/` — FastAPI routes, match engine and tests
- `apps/web/` — React replay dashboard and personas
- `apps/web/src/match.ts` — synthetic match fixture and frontend types

## Hackathon demo outline

1. Introduce the same fictional match and the three personas.
2. Play a goal in Young Fan mode; show the celebration and football word explanation.
3. Switch to Accessible; demonstrate high contrast, large text, keyboard navigation and optional narration.
4. Switch to Analyst; inspect half-by-half counts, weighted momentum and turning points.
5. Explain that all claims are grounded in synthetic events, and clearly separate required Foundry model integration from the deterministic fallback, and demonstrate a verified live model call only after Azure deployment.

**Every fan belongs. Every moment matters.**
