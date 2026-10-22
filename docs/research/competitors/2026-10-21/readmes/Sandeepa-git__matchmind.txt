# MatchMind ⚽🧠
**Explainable match intelligence**: live momentum, evidence-backed "Why?" cards, persona-based recaps in many languages, and an analyst you can ask questions.
Built for *Inside the Game: Microsoft × Premier League Developer Hackathon*.

## Features
| Feature | How |
|---|---|
| **Multi-agent production** | `agents.py`: Microsoft Agent Framework workflow. Detector → Analyst → Narrator ⇄ **FactChecker** → Localizer, sharing one `MatchContext` |
| **Self-correction** | The FactChecker rejects unsupported claims (scorelines, minutes, hat-tricks, plus an LLM groundedness check). The Narrator rewrites from that feedback, and after 2 failures a Fallback agent builds a template recap from verified data only |
| Live replay + momentum / xG | `api/matchmind/metrics.py`: rolling threat window over the event stream |
| Key-moment detection | Goals, big chances (xG ≥ 0.3), momentum flips |
| **Explainable "Why?" cards** | Tool-calling agent (`analyst.py`) on Microsoft Foundry gpt-5-mini. It must cite event IDs, which the UI shows as evidence |
| Recap studio | 4 personas × 3 formats (TV script, social thread, article), gpt-5-mini |
| Multilingual | Azure AI Translator (8 languages, including Sinhala, Hindi and Arabic with RTL) |
| Ask the analyst | Grounded Q&A over 5-minute match chunks with citations (upgrade path: Azure AI Search) |
| Cost control | Every LLM output is cached on disk (`api/cache/`), so a demo costs ~$0 after the first run |

## Agent workflow
```
Detector ─▶ Analyst ─▶ Narrator ─▶ FactChecker ──pass──▶ Localizer ─▶ output
                          ▲             │
                          └──reject─────┤  (feedback, ≤2 retries)
                                        └──give up──▶ Fallback ─▶ Localizer
```
The UI shows every handoff live. Tick **Stress test** to inject a hallucination and watch the FactChecker catch it and the Narrator fix it.

## Architecture
```
 synthetic events ─▶ metrics engine ─▶ key moments ─▶ Foundry agent (tools: events_before,
       (data/)        (momentum, xG)                    team_stats, player_involvement)
                                                              │
 React (Static Web Apps) ◀── Azure Functions API ◀────────────┤
   momentum chart, Why? cards,   /state /why /produce /ask     ├─▶ gpt-5-mini recaps 
   recap studio, chat                                         └─▶ Azure AI Translator
```

## Run locally (works without Azure keys in mock mode)
```bash
cd api
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy local.settings.json.example local.settings.json
python ../scripts/demo_cli.py          # terminal demo
func start                             # API on :7071
```
In another terminal:
```bash
cd web
npm install
npm run dev                            # http://localhost:5173
```

## Tests & CI
`cd api && pip install -r requirements-dev.txt && pytest`. GitHub Actions runs the tests and the web build on every push.

## Turn on Azure AI
```powershell
az login
./infra/setup.ps1      # creates Foundry/OpenAI + Translator and writes .env
```
Copy the same keys into `api/local.settings.json`. Set a **$100 budget alert** in Cost Management.

## Use the official hackathon dataset
Put the file in `api/data/` and edit `normalize()` in `api/matchmind/data.py` to map it to the schema:
`id, minute, second, team (home/away), player, type, x, y, xg, outcome`.

## Deploy (Azure Static Web Apps, free tier, includes the API)
```bash
az staticwebapp create -n matchmind-web -g matchmind-rg --source https://github.com/<you>/matchmind --branch main --app-location web --api-location api --output-location dist --login-with-github
```
Then add the env vars under Static Web App → Environment variables.

## Responsible AI
- Explanations are grounded in tool output, and each one cites the event IDs it relies on.
- Answers state a confidence level, and the analyst says so when the data can't answer a question.
- All data is synthetic, with no real personal data.

## Built with
GitHub, GitHub Copilot, Microsoft Agent Framework, Microsoft Foundry (Azure OpenAI), Azure AI Translator, Azure Functions, Azure Static Web Apps.

> After judging: `az group delete -n matchmind-rg` to stop all charges.
