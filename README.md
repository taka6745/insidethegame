# Inside the Game

Live football, shared match narratives and a personal match companion.

**Watch the match, and ask it anything.** Pick a live match. You get live stats and narratives framed for your team and style, and you can ask questions or request replays in chat. Code computes every number: ETL owns the statistics, and agents only choose what to show and how to explain it. One shared narrative pass serves every viewer in an audience, not one model call per viewer.

![Five services and their data flows, with status](architecture.svg)

## What works today

> **In short:** a judge opens the URL, presses **Start demo**, picks a start point and watches three live matches with the story so far. Deployed on Azure ([status](PLAN.md#11-azure-judge-build)) and tested on the local stack; open checks are in [PLAN.md §10.4](PLAN.md#104-azure-demo-acceptance-before-submission).

| | |
| --- | --- |
| **Demo URL** | `https://msft-hackathon.koda-software.com` ([edge proxy](edge-proxy/README.md)) |
| **Azure** | `./dev azure up` · [deployment](terraform/docs/deployment.md) |
| **Models on Azure** | Foundry `gpt-6.1-sol` (deployments `writer`, `questions`; effort low) for every agent · `Microsoft-Decision-1` for claim checks, follow triggers, clips and follow offers |
| **Spend** | Budgets email only; Stream Analytics runs only while match events flow; one last resort at 90 % of the credit ([guard](terraform/docs/components/guard.md)) |

Every feature below is implemented, unit-tested and run on the local Docker stack. On Azure, as an anonymous viewer, we verified 20′, HT and 60′ starts, Skip ahead, Cancel, questions, follows and capture cards; the 85′ seed is recorded, but kickoff and 85′ starts are not yet exercised through the edge.

- **Start demo.** Always exactly three matches; the main game (Redcastle Town–Port Albion) starts first and opens by default. Start points kickoff, 20′, HT, 60′, 85′; a second click joins the live demo; **Skip ahead** jumps +10′, +20′ or to the second half; **Cancel demo** purges everything. A seven-stage progress screen lights each stage from a real readiness check.
- **Seeds.** Mid-match starts restore a snapshot recorded on this pipeline, then the feed continues live: "story so far generated earlier on this pipeline; live from N′". Restore runs through a **demo-only adapter** in each owner, mounted only with `DEMO_SEEDS=1` (demo build; off in a release).
- **Three live matches.** Tactically scripted 90-minute simulations stream as HLS while their Opta-style events flow through Event Hubs; each run is its own `matchId`, purged on its own.
- **One ETL pipeline.** Stream Analytics writes events, SPADL actions, stats and trends to Azure SQL; Data API builder serves GraphQL; Service Bus carries notifications.
- **Storylines.** Agent Framework agents keep shared memory in Cosmos DB; an analyst finds grounded trends and the author develops storylines per enabled audience bucket (team × style × length). Decision-1 checks claims.
- **Follows and clips.** Viewers follow a story in the follow view; Decision-1 decides when it moves and which moments earn a clip. Key-event clips also reach shared Insights. Every clip gets a preview card, slow motion into the moment and the league sting between clips.
- **Cross-game.** Ask about, pin from or follow another live match from the same chat; its cards carry a yellow outline and that match's header. "Follow this story?" offers a follow after a story answer.
- **Questions, replays, receipts.** Answers route to ETL stats, a validated custom-stat compiler, match context or replay clips, each with facts, tokens, time and an estimated cost.
- **Developer screen `/dev/`.** Matches, prompts, audiences, models per role, demo settings, clip and playback tunables, prices.

```sh
ACCEPT_EULA=Y ./dev up backend      # accepts the Microsoft emulator licences: read local/README.md first
```

Open the [match viewer](http://localhost:18020) and press **Start demo**, or use the [developer screen](http://localhost:18020/dev/). **[Build locally →](DEVELOPMENT.md)**

## Judging criteria

| Criterion | Where to look |
| --- | --- |
| Technological implementation | Five services with their own contracts, tests and docs. [CI](.github/workflows/ci.yml) runs every suite plus Terraform checks. All data is synthetic and labelled ([data generation](data-generation/README.md)). |
| Agentic design and innovation | Multi-agent narrative engine: summarise, compress, then an analyst turns ETL trends into grounded storylines that the author develops per bucket, under one global model gate; Microsoft-Decision-1 checks claims, decides when a followed story moves and which moments earn a clip ([engine](narrative-engine/docs/architecture.md)). Question agents route questions to tools and compile custom stats into a bounded rule DSL, never into generated Python ([question agent](user-backend/docs/components/agents.md#2-question-agent)). |
| Real-world impact | Event-driven, per-match isolation, purge per match. Future data can't be reached. [Azure deployment gaps](terraform/docs/decisions.md#2-before-a-production-release). |
| UX and presentation | Start demo with live start progress, HLS viewer, cards, chat with replays and receipts, follow view with clip preview cards, slow motion and the sting, cross-game cards ([frontend](frontend/README.md)). |
| Hackathon category | Azure AI Foundry and Agent Framework agents on an Azure event-driven data platform. |

| Microsoft / Azure technology | Used for | Status |
| --- | --- | --- |
| **Azure AI Foundry** (Azure OpenAI `gpt-6.1-sol`) | Narrative agents (`writer`), question, replay and follow-planner agents (`questions`); effort low; `gpt-6-luna` and `gpt-5-mini` selectable per role | Deployed ([engine](narrative-engine/infra/variables.tf), [app](terraform/variables.tf)) |
| **Microsoft-Decision-1** (Foundry) | Claim checks, story-follow triggers, clip choice, follow offers | Deployed ([engine infra](narrative-engine/infra/variables.tf)); dev deployment used locally |
| **Microsoft Agent Framework** | Narrative agents; question, replay and custom-stat agents | Deployed; tested locally |
| **Azure Event Hubs** | `match-events` stream, partitioned by `matchId` | Deployed; emulator locally |
| **Azure Stream Analytics** | ETL job: events → key events, stats, notifications; runs only while events flow | Deployed; local Python stand-in with the same rules |
| **Azure SQL** | Event history, stats and trends (`statsAtSeq`, `trendsAtSeq`) | Deployed; SQL Server locally |
| **Data API builder** | ETL GraphQL | Deployed (internal ingress); container locally |
| **Azure Service Bus** | `match-notifications`, `narratives` (narratives and clips) | Deployed; emulator locally |
| **Azure Cosmos DB** | Narrative memory, narratives, storylines, checkpoints | Deployed; emulator locally |
| **Azure Container Apps** | Every service plus demo control; only the frontend is public | Deployed (`./dev azure up`) |
| **Azure Files** | Demo seeds, mounted into demo control (demo build only) | Deployed; `.local/seeds/` locally |
| Azure Monitor budgets + Automation | Spend guard: budget emails, Stream Analytics schedule, last resort | Deployed ([guard](terraform/guard/)) |
| Azure Database for PostgreSQL | Profiles, sessions, config, follows, clips, custom stats; the feed's runs | Deployed; PostgreSQL 16 locally |

## Disclosure

- **Synthetic data.** Every match is a simulation rendered with [Google Research Football](https://github.com/google-research/football) (Apache-2.0). None is a real fixture or Stats Perform data. The league, clubs and players are invented (the fictional Elephant League), and their events are simulated ([data generation](data-generation/README.md)).
- **AI.** Narratives, answers, clip and replay choices are generated by AI models at run time and labelled synthetic. Locally they use a local model; in Azure, Foundry deployments. Seeded starts replay a story generated earlier on the same pipeline and say so.
- **Artwork.** The league wordmark, club crests and clip sting are original project artwork; the only third-party mark is the Microsoft logo in the "Built with Microsoft Agent Framework" attribution ([frontend](frontend/README.md)).

## Services

| Folder | What it does | Docs |
| --- | --- | --- |
| [data-generation](data-generation/) | Rendered recordings, plus the **feed**: a simulated external provider (Event Hubs + played HLS) and the demo runs | [docs](data-generation/docs/README.md) |
| [etl](etl/) | Store events, calculate match statistics and serve them through GraphQL | [docs](etl/docs/README.md) |
| [narrative-engine](narrative-engine/) | Shared match memory, storylines, follow narratives and clips for active audience buckets | [docs](narrative-engine/docs/README.md) |
| [user-backend](user-backend/) | Questions, custom stats, replays, follows, clips, cross-game and live delivery for each viewer | [docs](user-backend/docs/README.md) |
| [frontend](frontend/) | Start demo, viewer, follow view, lab and `/dev/` screen | [docs](frontend/README.md) |
| [local](local/README.md) | Local stack and the demo operator: start, cancel, skip, status, seed record and restore (`/demo-api/`) | [docs](local/docs/README.md) |
| [edge-proxy](edge-proxy/) | Cloudflare Worker serving the demo URL | [README](edge-proxy/README.md) |

**Boundaries.** Our services see the feed only through Event Hubs and HLS over HTTP. The backend reads match data only through ETL GraphQL. The backend owns audience definitions and prompts. The engine frames each narrative for its bucket, and the backend routes it unchanged. Viewer questions never trigger the shared narrative workflow. [Contracts](local/contracts/README.md).

[Development practices](DEVELOPMENT-PRACTICES.md) · [Local Docker setup](local/README.md) · [Terraform](terraform/README.md) · [Plan and open items](PLAN.md) · [Target plan (Excalidraw)](master-plan.excalidraw) · [Archived research](legacy/README.md) ([competitor refresh, 21 Oct](legacy/research/competitors/2026-10-21/README.md))

Render the diagrams with `python3 .github/scripts/render_architecture.py`, `render_development.py` and `render_master_plan.py` (then export the Excalidraw scene to `master-plan.svg`). The icons are local renders (`.github/diagram-assets/`) from the preserved [engineering library](legacy/docs/icon-libraries/README.md); its [sources](legacy/docs/icon-libraries/sources.json) and [licence](legacy/docs/icon-libraries/EXCALIDRAW-LIBRARIES-LICENSE) hold the provenance. They identify technologies, not endorsement.
