# MatchMind AI

AI-powered live football intelligence prototype. Synthetic match events become explainable insights and personality-driven commentary.

## What this MVP includes

- Simulated live match (fictional teams: Northbridge FC vs Riverton United)
- Event timeline (passes, shots, tackles, goals, and more)
- Deterministic match statistics
- Rule-based insights with **what happened**, **why it matters**, evidence, and match time
- Three original host personalities (entertainment, Hinglish, tactical analyst)
- `/api/commentary` — server route that rewrites verified facts in the selected host voice
- **Multi-agent pipeline** — Event Analyst → Tactical State → Insight → Narrative → Personalization
- **Viewing modes** — analyst, casual fan, club supporter (home/away), player focus
- **Match recap** — automated key-moment story from verified events
- **Overlay JSON** — machine-readable broadcast packet (`/api/overlay` + in-app copy)

This version does **not** yet use real Premier League data. Azure AI is optional: without credentials the app uses the built-in agent/rules hosts.

## Run locally

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Optional: connect Azure OpenAI / Foundry

1. Copy `.env.example` to `.env.local`
2. Fill in your endpoint, API key, and deployment name
3. Restart `npm run dev`

When configured, the commentary badge shows **AI model**. When missing or failing, it shows **Rules fallback**.

Check status anytime:

```bash
curl http://localhost:3000/api/commentary
```

## MVP checklist

1. Click **Start match** — the clock advances
2. Watch the **event timeline** fill with synthetic events
3. Confirm **statistics** update
4. Read the **insight** evidence and time window
5. Switch all three **hosts** — commentary style changes
6. Click **Reset** — score, clock, events, and stats clear

## Project layout

```
app/                      Next.js App Router pages + API routes
app/api/commentary/       AI commentary endpoint
components/               Match dashboard UI
lib/match/                Engine, insights, hosts, types
lib/ai/                   Prompting + Azure/Foundry client
```

## Next steps

1. Automated tests for the match engine and insight evidence
2. Richer event model (shot locations, player baselines)
3. Stronger output validation against the verified fact pack
4. Azure deployment + overlay JSON + demo video
