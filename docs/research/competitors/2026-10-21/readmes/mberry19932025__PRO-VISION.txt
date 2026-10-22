# PRO-VISION AI

**Ask about the game. Explore the evidence. Keep the moment.**

A working football intelligence and fan-memory prototype for the Microsoft × Premier League Inside the Game hackathon. It uses original fictional match events, server-side Azure AI and an interactive browser experience on desktop or mobile. It is an independent prototype, not an official Premier League service or real live match feed.

- [Open the live Azure app](https://provision-mberry-demo-h4b4bjh7fpapcgfp.westus3-01.azurewebsites.net/)
- [Canonical application source](competition-app/)
- [Architecture and Microsoft technology](competition-app/docs/ARCHITECTURE.md)
- [Submission status and testing instructions](competition-app/docs/SUBMISSION-CHECKLIST.md)

## Try it

Start in Chat with a suggested question. Open Match to choose a shot or replay the fictional match. Ask why a moment matters, inspect its cited records, then create your own photo or video-frame memory card in Studio. Flip/download it, return to its match moment, or preview the garment concept.

The Match report compares team statistics, shows the goal timeline and compares recorded player actions. These calculations and recaps use no model calls. The explicit Match Director action uses a bounded Azure function call to select a recorded moment, inspects its evidence, then requests an explanation. It permits at most two provider requests, rejects unknown tools/arguments and never selects beyond the replay cursor. Its visible trace distinguishes the Azure tool workflow from a rule-based fallback. This is a single-model tool workflow, not multi-agent orchestration.

## Run the actual deployed app

Node 24+ is required. The root scripts delegate to `competition-app/`:

```sh
npm ci --ignore-scripts
npm run build
npm test
npm run validate
npm run dev
```

Open http://localhost:4173. After source edits, rebuild and restart. For an offline local preview, open `competition-app/output/PRO-VISION-AI-Demo.html`; it labels its rule-based explanations and makes no cloud requests.

Configure `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_DEPLOYMENT` in an ignored `.env` for local development, or server-side Azure App Service environment variables. Never place a key in browser assets or a public repository. The endpoint must be an HTTPS Azure OpenAI/Foundry resource. API failures, rejected evidence and exhausted allowances use a labeled local fallback.

## Data and features

- 180 deterministic fictional events over a 90-minute match, two original clubs and ten players.
- Score, shots/on-target attempts, completed/attempted passes, pass accuracy, pressures, selected-event pass distance and time-bounded match reports.
- Fan/coach perspectives, team/player filters, English/Spanish narratives and local recaps.
- Conversation history, editable browser speech input, optional answer readout, evidence tours and recorded-data shortcuts.
- Bounded Azure Match Director, two-step function calling, validation, caching and persistent request controls.
- Personal photo/video-frame cards, SVG/PNG exports, replay links and a T-shirt concept. Personal media stays in the page and must be downloaded to keep it.

Coordinates are normalized toward the attacking goal for each possession. Distances assume a 105 × 68 m pitch. There is no video recognition, tracking, xG, player-intent inference, real fixtures feed, physical NFC integration or clothing production. Accepted AI interpretations can still be incorrect; evidence checks are not full factual verification.

## Hosting and cost controls

GitHub Actions builds/tests this app and deploys it to Azure App Service. Foundry/Azure OpenAI provides the model through the OpenAI-compatible Chat Completions and function-calling APIs. The optional native Foundry Local adapter is for local development.

Default Azure limits remain 20 attempted model requests per UTC day and 100 per UTC month, shared across visitors. A Director run can consume two attempts. Ordinary replay, recorded facts, reports and memory creation do not request AI. Successful AI results are cached; failed attempts count conservatively. Counts persist under `/home/provision/` on Azure. A damaged usage ledger disables AI without resetting counts; the rest of the app remains available. Use one server instance: this is not a distributed quota store or a dollar spending cap.

Free F1 hosting is configured. Actual subscription balance/billing must be checked in Azure. Credit expiry and unrestricted judge access remain owner decisions before submission; current shared AI caps can block judging requests.

## Verification and submission status

Automated tests cover football calculations, temporal grounding, conversation/controller flows, speech fallbacks, reports, cards, quotas and mocked Azure tool execution. Live Azure narrative generation has previously been verified. Fresh desktop/mobile visual, microphone, video and download checks need a connected browser or real-device review; simulated DOM tests do not replace them.

Registration, a publicly hosted demo-video URL, category selection and final submission are still pending. Do not treat a local MP4 as the required public video link. [Official competition rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md).

Older files under root `src/`, `server.mjs` and root `docs/` describe an archived nine-event prototype. They are retained for history; Azure starts `competition-app/scripts/dev.mjs`. Use the explicitly named `legacy:*` scripts only when working on that archived version.
