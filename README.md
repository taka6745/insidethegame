# Inside the Game

Live football, shared match narratives and a personal match companion.

**Watch the match, and ask it anything.** Pick a live match. You get live stats and narratives framed for your team and style, and you can ask questions or request replays in chat. Code computes every number: ETL owns the statistics, and agents only choose what to show and how to explain it. One shared narrative pass serves every viewer in an audience, not one model call per viewer.

![Five services and their data flows, with status](architecture.svg)

## What works today

> **In short:** a judge opens the URL, presses **Start demo**, picks a start point and watches three live matches with the story so far. Applied on Azure 22 Oct for the Azure test; the demo acceptance ([PLAN.md §10.4](PLAN.md#104-azure-demo-acceptance-before-submission)) is pending.

| | |
| --- | --- |
| **Judge URL** | `https://msft-hackathon.koda-software.com` ([edge proxy](edge-proxy/README.md), deployed 22 Oct) |
| **Azure** | `./dev azure up` (applied 22 Oct; acceptance pending) · [runbook](terraform/runbook.md) |
| **Models on Azure** | Foundry `gpt-6.1-sol` (deployments `writer`, `questions`; in Terraform, being rolled out) · `Microsoft-Decision-1` (applied) |
| **Spend** | Budgets email only; Stream Analytics runs only while match events flow; one last resort at 90 % of the credit ([guard](terraform/runbook.md#4-spend-guard-and-idle-saver)) |

Status key: **deployed** = applied on Azure 22 Oct; **tested** = unit tests plus a run on the local Docker stack ([PLAN.md §10.7](PLAN.md#107-local-integration-check-22-oct-evening)); **built** = code and unit tests, live check pending.

- **Start demo** (tested; deployed). Always exactly three matches; the main game (Arsenal–Liverpool) starts first and opens by default. Start points kickoff, 20′, HT, 60′, 85′; a second click joins the live demo; **Cancel demo** purges everything. A seven-stage progress screen lights each stage from a real readiness check.
- **Seeds** (tested locally). Mid-match starts restore a snapshot recorded on this pipeline, then the feed continues live: "story so far generated earlier on this pipeline; live from N′". Restore runs through a **demo-only adapter** in each owner, mounted only with `DEMO_SEEDS=1` (judge build; off in a release).
- **Three live matches** (tested; deployed). Tactically scripted 90-minute simulations stream as HLS while their Opta-style events flow through Event Hubs; each run is its own `matchId`, purged on its own.
- **One ETL pipeline** (deployed). Stream Analytics writes events, SPADL actions, stats and trends to Azure SQL; Data API builder serves GraphQL; Service Bus carries notifications.
- **Storylines** (tested; deployed). Agent Framework agents keep shared memory in Cosmos DB; an analyst finds grounded trends and the author develops storylines per enabled audience bucket. Decision-1 checks claims.
- **Follows and clips** (built). Viewers follow a story in the follow view; Decision-1 decides when it moves and which moments earn a clip. Key-event clips also reach shared Insights. Every clip gets a preview card, slow motion into the moment and the league sting between clips.
- **Cross-game** (built). Ask about, pin from or follow another live match from the same chat; its cards carry a yellow outline and that match's header. "Follow this story?" offers a follow after a story answer.
- **Questions, replays, receipts** (tested; deployed). Answers route to ETL stats, a validated custom-stat compiler, match context or replay clips, each with facts, tokens, time and an estimated cost.
- **Developer screen `/dev/`** (tested). Matches, prompts, audiences, demo settings, clip and playback tunables, prices.

```sh
ACCEPT_EULA=Y ./dev up backend      # accepts the Microsoft emulator licences: read local/README.md first
```

Open the [match viewer](http://localhost:18020) and press **Start demo**, or use the [developer screen](http://localhost:18020/dev/). **[Build locally →](DEVELOPMENT.md)**

## Judging criteria

| Criterion | Where to look |
| --- | --- |
| Technological implementation | Five services with their own contracts, tests and docs. [CI](.github/workflows/ci.yml) runs every suite plus Terraform checks. All data is synthetic and labelled ([recordings](data-generation/recordings/README.md)). |
| Agentic design and innovation | Multi-agent narrative engine: summarise, compress, then an analyst turns ETL trends into grounded storylines that the author develops per bucket, under one global model gate; Microsoft-Decision-1 checks claims, decides when a followed story moves and which moments earn a clip ([engine](narrative-engine/docs/architecture.md)). Question agents route questions to tools and compile custom stats into a bounded rule DSL, never into generated Python ([question agent](user-backend/docs/components/agents.md#2-question-agent)). |
| Real-world impact | Event-driven, per-match isolation, purge per match. Future data can't be reached. [Azure deployment gaps](terraform/deployment-readiness.md). |
| UX and presentation | Start demo with live start progress, HLS viewer, cards, chat with replays and receipts, follow view with clip preview cards, slow motion and the sting, cross-game cards ([frontend](frontend/README.md)). |
| Hackathon category | Azure AI Foundry and Agent Framework agents on an Azure event-driven data platform. |

| Microsoft / Azure technology | Used for | Status |
| --- | --- | --- |
| **Azure AI Foundry** (Azure OpenAI `gpt-6.1-sol`) | Narrative agents (`writer`), question, replay and follow-planner agents (`questions`); effort low | In Terraform ([engine](narrative-engine/infra/variables.tf), [app](terraform/variables.tf)); rollout to the applied stack pending |
| **Microsoft-Decision-1** (Foundry) | Claim checks, story-follow triggers, clip choice; follow offers locally (Azure backend falls back to `questions`) | Deployed 22 Oct ([engine infra](narrative-engine/infra/variables.tf)); dev deployment used locally |
| **Microsoft Agent Framework** | Narrative agents; question, replay and custom-stat agents | Deployed 22 Oct; tested locally |
| **Azure Event Hubs** | `match-events` stream, partitioned by `matchId` | Deployed 22 Oct; emulator locally |
| **Azure Stream Analytics** | ETL job: events → key events, stats, notifications; runs only while events flow | Deployed 22 Oct (live run pending); local Python stand-in with the same rules |
| **Azure SQL** | Event history, stats and trends (`statsAtSeq`, `trendsAtSeq`) | Deployed 22 Oct; SQL Server locally |
| **Data API builder** | ETL GraphQL | Deployed 22 Oct (internal ingress); container locally |
| **Azure Service Bus** | `match-notifications`, `narratives` (narratives and clips) | Deployed 22 Oct; emulator locally |
| **Azure Cosmos DB** | Narrative memory, narratives, storylines, checkpoints | Deployed 22 Oct; emulator locally |
| **Azure Container Apps** | Every service plus demo control; only the frontend is public | Deployed 22 Oct (`./dev azure up`) |
| **Azure Files** | Demo seeds, mounted into demo control (judge build only) | Deployed 22 Oct; `.local/seeds/` locally |
| Azure Monitor budgets + Automation | Spend guard: budget emails, Stream Analytics schedule, last resort | Deployed 22 Oct ([guard](terraform/guard/)) |
| Azure Database for PostgreSQL | Profiles, sessions, config, follows, clips, custom stats; the feed's runs | Deployed 22 Oct; PostgreSQL 16 locally |

## Disclosure

- **Synthetic data.** Every match is a simulation rendered with [Google Research Football](https://github.com/google-research/football) (Apache-2.0). None is a real fixture or Stats Perform data. Club and player names are illustrative, and their events are simulated ([recordings](data-generation/recordings/README.md)).
- **AI.** Narratives, answers, clip and replay choices are generated by AI models at run time and labelled synthetic. Locally they use a local model; in Azure, Foundry deployments. Seeded starts replay a story generated earlier on the same pipeline and say so.
- **Third-party marks.** The viewer uses club crests and league typefaces for the demo. They belong to their owners and aren't licensed to this project ([open items](docs/reviews/hackathon-readiness.md#3-submission-blockers)).

## Services

| Folder | What it does | Status |
| --- | --- | --- |
| [data-generation](data-generation/) | Rendered recordings, plus the **feed**: a simulated external provider (Event Hubs + played HLS) and the demo runs | Deployed 22 Oct · tested locally · [docs](data-generation/docs/README.md) |
| [etl](etl/) | Store events, calculate match statistics and serve them through GraphQL | Deployed 22 Oct · tested locally · [docs](etl/docs/README.md) |
| [narrative-engine](narrative-engine/) | Shared match memory, storylines, follow narratives and clips for active audience buckets | Deployed 22 Oct · tested locally · [docs](narrative-engine/docs/README.md) |
| [user-backend](user-backend/) | Questions, custom stats, replays, follows, clips, cross-game and live delivery for each viewer | Deployed 22 Oct · tested locally · [docs](user-backend/docs/README.md) |
| [frontend](frontend/) | Start demo, viewer, follow view, lab and `/dev/` screen | Deployed 22 Oct · tested locally |
| [local/demo_control.py](local/README.md) | Demo operator: start, cancel, status, seed record and restore (`/demo-api/`) | Deployed 22 Oct · tested locally |
| [edge-proxy](edge-proxy/) | Cloudflare Worker serving the judge URL | Deployed 22 Oct |

**Boundaries.** Our services see the feed only through Event Hubs and HLS over HTTP. The backend reads match data only through ETL GraphQL. The backend owns audience definitions and prompts. The engine frames each narrative for its bucket, and the backend routes it unchanged. Viewer questions never trigger the shared narrative workflow. [Contracts](local/contracts.md).

[Development practices](DEVELOPMENT-PRACTICES.md) · [Local Docker setup](local/README.md) · [Terraform](terraform/README.md) · [Hackathon readiness](docs/reviews/hackathon-readiness.md) · [Target plan (Excalidraw)](master-plan.excalidraw) · [Archived research](legacy/README.md)

[Competitor refresh · 21 October](docs/research/competitors/2026-10-21/README.md): 472 projects, 77 repo links and 64 public repositories; full descriptions and pinned READMEs saved.

Render the diagrams with `python3 .github/scripts/render_architecture.py`, `render_development.py` and `render_master_plan.py` (then export the Excalidraw scene to `master-plan.svg`). The icons come from the preserved [engineering library](legacy/docs/icon-libraries/README.md) ([attribution](.github/diagram-assets/README.md)).
