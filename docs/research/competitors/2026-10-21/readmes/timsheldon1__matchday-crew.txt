# Matchday Crew

Explainable, personalised match intelligence from a team of AI agents.
Built for the Microsoft + Premier League *Inside the Game* Developer Hackathon (2026).

> Status: generator, Analyst, AI crew (Explainer, Storyteller, Recapper on Microsoft Foundry), live React overlay with voice, and Azure Container Apps deployment are in place.

## Pipeline

```
Data (synthetic events) -> Analyst (stats, key moments) -> Explainer (why it matters)
      -> Storyteller (commentary + recaps, EN / SW / JA) -> Personalizer (fan, analyst, player focus)
      -> React overlay
```

## Synthetic match generator

The generator and Analyst have zero dependencies. Needs Node 22 or newer (required by the Foundry SDK).

```bash
npm test                                          # 45 tests: generator, Analyst, crew, team shape and voice
node src/cli.js generate --seed 42                # writes data/match-NNS-KLS-42.json and prints a box score
node src/cli.js stats --seed 7 --home RVU --away HLA
node src/cli.js stream --seed 42 --speed 30       # live NDJSON on stdout, 90 minutes in ~3 minutes
node src/cli.js calibrate --n 300                 # realism check across many matches
node src/cli.js analyse --seed 42                 # key moments the Analyst finds, plus top-rated players
node src/cli.js accuracy --n 100                  # Analyst momentum vs the generator's hidden truth
node src/server.js                                # HTTP + Server-Sent Events on port 4000
```

Server endpoints:

- `GET /matches/:seed` returns the full match (meta and events)
- `GET /matches/:seed/stream?speed=30` streams live as SSE: `match_event`, `moment` (from the Analyst) and `stats` (live snapshot). Supports `Last-Event-ID` to resume
- `GET /matches/:seed/analysis` returns every key moment plus the final stats
- `GET /clubs`, `GET /health`

### What it simulates

- Four fictional clubs with their own style (pressing, directness, quality) and generated squads
- Passes with distance, progression, difficulty and pressure; carries with sprint speeds; pressing, tackles, interceptions
- Shots with an expected-goals (xG) model, shot speed, saves, blocks, corners, free kicks, penalties
- Fouls, yellow and red cards, three substitutions per team, stoppage time
- Hidden momentum swings that change how teams play, for the Analyst to detect

Every match is fully repeatable from its seed, which keeps demos and tests stable.

### Realism check (300 matches, per team per match)

| Metric | Generator | Real top-flight (approx.) |
|---|---|---|
| Goals | 1.6 | 1.4 |
| Shots | 12.1 | 12 to 13 |
| On target | 4.8 | 4 to 5 |
| Pass accuracy | 79% | 80 to 85% |
| Corners | 5.1 | 5 |
| Fouls | 12.3 | 10 to 11 |
| Yellow cards | 1.6 | 1.8 |

Event format: see [SCHEMA.md](SCHEMA.md).

## Analyst

`src/analyst.js` reads events one at a time, as they happen, and keeps live team and player stats. It also flags key moments. It is plain code with no AI calls, so it is instant and its numbers are always right. The AI agents build on its output instead of guessing at stats.

Each moment includes the type, importance (0 to 1), the players involved, the evidence (`facts` and `eventIds`) and a template `headline`. The headline is the fallback the overlay shows if an AI agent is slow or fails.

| Moment | What triggers it |
|---|---|
| `goal` | Every goal, with context: opener, equaliser, go-ahead, against the run of play, brace |
| `big_chance` | Missed or saved shot worth 0.30 xG or more |
| `momentum_swing` | One team's threat over the last 5 minutes clearly outweighs the other's |
| `rhythm_shift` | Control vs chaos: possession changing hands much less or much more than normal |
| `pressing_spell` | Unusually heavy pressing that is winning the ball back high up the pitch |
| `xg_vs_score` | A team is creating far more but not winning |
| `penalty_awarded`, `red_card`, `yellow_card`, `substitution` | As named |
| `speed_alert`, `rocket_shot`, `quality_pass` | Overlay triggers: sprint 33 km/h or more, shot 110 km/h or more, hard progressive pass |
| `half_time`, `full_time` | Full stats snapshot for recaps |

### How we know the momentum read works

The generator simulates a hidden momentum value that the Analyst never sees. Over 100 matches:

- The Analyst's momentum index correlates with the hidden truth at **r = 0.48**
- **72%** of its momentum swing calls point at the team that really was on top

Run `node src/cli.js accuracy --n 100` to reproduce.

## AI crew (Microsoft Foundry)

Three prompt agents run on a `gpt-5-mini` deployment in Microsoft Foundry, registered and versioned in the project so they show up in the Foundry portal:

| Agent | Input | Output |
|---|---|---|
| `matchday-explainer` | One key moment from the Analyst plus live context | Why it matters, a tactical angle, the key numbers, a confidence level |
| `matchday-storyteller` | The moment, the Explainer's insight, persona, languages, lines already on screen | One broadcast line per language (English, Swahili, Japanese) |
| `matchday-recapper` | Half-time or full-time stats, top players, the key moments and their explanations | A short recap and player of the match in each language |

`src/agents/crew.js` orchestrates them around a shared match state:

- **Handoffs:** Analyst (code) to Explainer to Storyteller, with the Recapper at half time and full time
- **Shared state:** every agent sees recent insights and the lines already on screen, so commentary does not repeat
- **Live priorities:** a priority queue handles goals and big moments first and drops low-value moments when the crew falls behind live play (goals and recaps are never dropped)
- **Guardrails:** strict JSON schema output, plus a grounding check that rejects any number not present in the Analyst's evidence. A rejected answer gets one retry with feedback
- **Recovery:** on a timeout, an error or an ungrounded answer, the crew shows template text in all three languages so the screen never goes blank, and records what happened in a crew report (calls ok, retries, fallbacks, latency)
- **Two call paths:** registered Foundry agents first, called by name and their latest version. If an agent call is rejected, that one call goes straight to the model with the same instructions and the next call tries the agent again. After 3 failures in a row that agent stays on direct calls, and the server log says why

```bash
npm run crew:offline       # full match with template fallbacks, no Azure needed
npm run crew:check         # one test call to Foundry
npm run crew:deploy        # register the three agents in your Foundry project
npm run crew:live          # full match with live AI commentary in English, Swahili and Japanese
```

The server can stream the commentary too: `GET /matches/42/stream?speed=30&crew=1&langs=en,sw,ja&persona=analyst` adds `commentary` events and a final `crew_report`.

### Azure setup

1. Create a Foundry project at ai.azure.com and deploy `gpt-5-mini` (we named the deployment `matchday-mini`).
2. Copy `.env.example` to `.env` and set `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL_DEPLOYMENT`.
3. Sign in with the Azure CLI. Auth is Microsoft Entra ID, so there are no API keys in the code:
   ```bash
   az login --tenant <your-tenant-id> --use-device-code
   ```
4. If `crew:check` returns 401 or 403, give yourself the **Azure AI User** role on the Foundry resource:
   ```bash
   az role assignment create --role "Azure AI User" --assignee-object-id <your-user-object-id> --assignee-principal-type User --scope <foundry-resource-id>
   ```
   Your object id: `az ad signed-in-user show --query id -o tsv`. The resource id is on the resource's Overview page under JSON view.

## Live overlay (React)

`web/` is a Vite + React app that plays the match live from the server stream and shows what the crew produces:

- **Pitch view** with all 22 players in club colours and shirt numbers, the ball and the player on it, a Names toggle, sprint and shot-speed tags, and a broadcast lower third for big AI lines. Player positions come from a team shape model (`web/src/teamShape.js`): each team's 4-3-3 block slides with the ball, the team in possession pushes up and spreads wide, the defending team drops and narrows, and the nearest defender steps in to press. The generator only tracks the ball, so these positions are a realistic simulation, not tracking data
- **Voice commentary** (Voice button): big moments and recaps are spoken in English, Swahili or Japanese with Azure AI Speech neural voices (`en-GB-RyanNeural`, `sw-KE-RafikiNeural`, `ja-JP-KeitaNeural`), one line at a time so the voice never falls behind. If Speech is not configured, the browser's own voice is used where one exists
- **Score bar** with clock, live momentum meter and a control vs chaos badge
- **Match story feed:** every Analyst moment appears instantly, then the AI line fills in a few seconds later. Each card shows whether it came from the AI or a template, and how long the crew took
- **Personalisation:** English, Swahili or Japanese at the flip of a switch; Fan view (story) or Analyst view (why it matters, tactical angle, key numbers, confidence); follow a club; player focus mode that tracks one player on the pitch and filters the story to their moments
- **Momentum timeline** with goals marked, live stats bars, top-rated players, and an AI crew panel showing the Analyst to Explainer to Storyteller handoff with status and latency
- **Recap pop-up** at half time and full time from the Recapper agent

```bash
npm run build     # builds the overlay into web/dist
npm start         # serves the API and the overlay on http://localhost:4000
```

For overlay development with hot reload, run `npm start` in one terminal and `npm run web:dev` in another, then open http://localhost:5173.

### Voice setup (Azure AI Speech)

Speech uses the same Foundry resource and the same Entra ID sign-in as the agents. Add to `.env`:

```bash
SPEECH_REGION=<your resource region, e.g. eastus2>
SPEECH_RESOURCE_ID=/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<resource>
```

Then `npm run voice:check` writes a test MP3 per language to `data/`. If it returns 401, give yourself the **Cognitive Services Speech User** role on the resource (same command as in Azure setup, with that role name), or set `SPEECH_KEY` in `.env` as a fallback.

## Deployment (Azure Container Apps)

```
git push  ->  GitHub Actions: npm test, build image  ->  ghcr.io/timsheldon1/matchday-crew
                                                              |
                     Azure Container Apps (scale 0 to 2)  <---+
                       | managed identity, no keys
                       +--> Microsoft Foundry agents (Azure AI User role)
                       +--> Azure AI Speech (Cognitive Services Speech User role)
```

- `Dockerfile` builds the overlay and the Node server into one small image
- `.github/workflows/container.yml` runs all tests, then publishes the image on every push to `main`
- `deploy/azure-deploy.ps1` creates or updates the Container App, turns on a system-assigned managed identity and grants it the two roles. Run it again to roll out a new image
- Cost guard: at most `MAX_CREW_STREAMS` (default 4) matches get live AI commentary at once; extra viewers still get the match with template commentary. Text to speech is rate limited

## Data and IP

All clubs, players and matches are fictional and generated. No real match footage, league data or club marks are used.
