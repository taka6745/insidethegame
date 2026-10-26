# Inside the Game

Live football, shared match narratives and a personal match companion.

**Watch the match, and ask it anything.** Pick a live match. You get live stats and narratives framed for your team and style, and you can ask questions or request replays in chat. Code computes every number: ETL owns the statistics, and agents only choose what to show and how to explain it. One shared narrative pass serves every viewer in an audience, not one model call per viewer.

![How the data flows: feed, Event Hubs, Stream Analytics, Azure SQL, narrative engine, Service Bus, user backend, frontend](architecture-overview.svg)

[Detailed architecture](architecture.svg) with deployment status, demo build and seeds.

## How it works

- A simulated provider streams each match's Opta-style events into Event Hubs and its footage as HLS; our services never see anything else, so a real provider swaps in at that seam ([data generation](data-generation/README.md)).
- Stream Analytics turns the events into key events and minute stats in Azure SQL, a post-processor adds SPADL actions, and Data API builder serves it all as GraphQL ([ETL](etl/README.md)).
- The narrative engine runs one shared pass per audience bucket (team × style × length), not one model call per viewer: summarise, compress, find grounded trends, develop storylines ([engine](narrative-engine/README.md)).
- Match memory keeps full detail for the last minutes and compresses older ones into coarser blocks, so the prompt stays small over 90 minutes ([context compression](narrative-engine/README.md#context-compression)); the author prompt puts the shared prefix first so Foundry can cache it, and cached tokens show in the metrics.
- Microsoft Decision-1, a bounded classifier rather than a text model, decides whether a claim is supported, when a followed story moves and which moments earn a clip.
- Viewer questions route to ETL stats, match context or replay clips; a custom stat is compiled into a validated rule DSL that code executes, never generated Python, and every answer carries its facts, tokens and cost ([user backend](user-backend/README.md)).
- Mid-match starts restore a snapshot recorded on this pipeline and hold nothing past the start point; all footage is our own, rendered with Google Research Football.

## Where next

- **Tap a player.** The feed already streams positions (POS), so player overlays on the footage and "who is that?" taps are a frontend step, not a data one.
- **Real provider.** Replace the simulator at the Event Hubs + HLS seam; nothing downstream changes.
- **More audiences and languages.** A bucket is configuration (team × style × length); a language is one more axis, with no engine change.
- **Release build.** `./dev azure up --release` deploys without demo control and seeds; the remaining gaps are listed in [terraform](terraform/README.md#decisions-and-production-gaps).

## What works today

A judge opens the URL, presses **Start demo**, picks a start point and watches three live matches with the story so far. Every feature below is implemented, unit-tested, run on the local Docker stack and checked on Azure.

| | |
| --- | --- |
| **Demo URL** | `https://msft-hackathon.koda-software.com` ([edge proxy](edge-proxy/README.md)) |
| **Azure** | `./dev azure up` ([terraform](terraform/README.md)) |
| **Models on Azure** | Foundry `gpt-6.1-sol` (deployments `writer`, `questions`; effort low) for every agent · `Microsoft-Decision-1` for claim checks, follow triggers, clips and follow offers |
| **Spend** | Budgets email only; Stream Analytics runs only while match events flow; a last resort at 90 % of the credit, a hard stop at 100 % ([guard](terraform/README.md#spend-guard)) |

- **Start demo.** Always exactly three matches; the main game (Redcastle Town–Port Albion) starts first and opens by default. Start points kickoff, 20′, HT, 60′, 85′; a second click joins the live demo; **Skip ahead** jumps +10′, +20′ or to the second half; **Cancel demo** purges everything. A seven-stage progress screen lights each stage from a real readiness check.
- **Seeds.** Mid-match starts restore a snapshot recorded on this pipeline, then the feed continues live ("live from N′"), through a demo-only adapter in each owner, mounted only with `DEMO_SEEDS=1`.
- **Three live matches.** Tactically scripted 90-minute simulations stream as HLS while their Opta-style events flow through Event Hubs; each run is its own `matchId`, purged on its own.
- **One ETL pipeline.** Stream Analytics writes events, key events and minute stats to Azure SQL; a post-processor adds SPADL actions; SQL procedures serve stats and trends; Data API builder serves GraphQL; Service Bus carries notifications.
- **Storylines.** Agent Framework agents keep shared memory in Cosmos DB; an analyst finds grounded trends and the author develops storylines per enabled audience bucket. Decision-1 checks claims.
- **Follows and clips.** Viewers follow a story; Decision-1 decides when it moves and which moments earn a clip. Every clip gets a preview card, slow motion into the moment and the league sting between clips.
- **Cross-game.** Ask about, pin from or follow another live match from the same chat; its cards carry a yellow outline and that match's header. "Follow this story?" offers a follow after a story answer.
- **Questions, replays, receipts.** Answers route to ETL stats, a validated custom-stat compiler, match context or replay clips, each with facts, tokens, time and an estimated cost.
- **Developer screen `/dev/`.** Matches, prompts, audiences, models per role, demo settings, clip and playback tunables, prices.

## Judging criteria

| Criterion | Where to look |
| --- | --- |
| Technological implementation | Five services with their own contracts, tests and READMEs. [CI](.github/workflows/ci.yml) runs every suite plus Terraform checks. All data is synthetic and labelled ([data generation](data-generation/README.md)). |
| Agentic design and innovation | Multi-agent narrative engine: summarise, compress, then an analyst turns ETL trends into grounded storylines that the author develops per bucket, under one global model gate; Microsoft-Decision-1 checks claims, decides when a followed story moves and which moments earn a clip ([engine](narrative-engine/README.md)). Question agents route questions to tools and compile custom stats into a bounded rule DSL, never into generated Python ([user backend](user-backend/README.md#how-it-works)). |
| Real-world impact | Event-driven, per-match isolation, purge per match. Future data can't be reached. [Production gaps](terraform/README.md#decisions-and-production-gaps). |
| UX and presentation | Start demo with live start progress, HLS viewer, cards, chat with replays and receipts, follow view with clip preview cards, slow motion and the sting, cross-game cards ([frontend](frontend/README.md)). |
| Hackathon category | Azure AI Foundry and Agent Framework agents on an Azure event-driven data platform. |

| Microsoft / Azure technology | Used for |
| --- | --- |
| **Azure AI Foundry** (Azure OpenAI `gpt-6.1-sol`) | Narrative agents (`writer`), question, replay and follow-planner agents (`questions`); `gpt-6-luna` and `gpt-5-mini` selectable per role |
| **Microsoft-Decision-1** (Foundry) | Claim checks, story-follow triggers, clip choice, follow offers |
| **Microsoft Agent Framework** | Narrative agents; question, replay and custom-stat agents |
| **Azure Event Hubs** | `match-events` stream, partitioned by `matchId` |
| **Azure Stream Analytics** | ETL job: events → key events, stats, notifications; runs only while events flow |
| **Azure SQL** | Event history, SPADL actions, stats and trends (`statsAtSeq`, `trendsAtSeq`) |
| **Data API builder** | ETL GraphQL |
| **Azure Service Bus** | `match-notifications`, `narratives` (narratives and clips) |
| **Azure Cosmos DB** | Narrative memory, narratives, storylines, checkpoints |
| **Azure Container Apps** | Every service plus demo control; only the frontend is public |
| **Azure Files** | Demo seeds, mounted into demo control (demo build only) |
| Azure Monitor budgets + Automation | Spend guard: budget emails, Stream Analytics schedule, last resort, hard stop |
| Azure Database for PostgreSQL | Profiles, sessions, config, follows, clips, custom stats; the feed's runs |

## Status

Submission closes 27 Oct 2026, 11:59 pm PT; the build stays up until judging ends (11 Nov, 5:59 pm AEST), then `./dev azure down`. Open submission items: [docs/submission.md](docs/submission.md).

| | |
| --- | --- |
| **Deployed** | Demo build on Azure (last deploy 26 Oct, `7208b2b`); every agent on `gpt-6.1-sol`; seeds 20′, HT, 60′, 85′ recorded on Azure; checked as an anonymous viewer: three matches, seeded insights, questions in about 6 s, cross-match follow catching up in about 10 s, a capture card played as a replay, Skip ahead, Cancel, "all goals across all games" as one reel |
| **Measured** | Seeded 60′ start 7.1 s, 20′ start 3.4 s, kickoff first picture about 20 s (about 40 s on cold apps); engine about 0.5 match minutes behind; no cross-match leak in scans; about US$2 of tokens per session of three matches to half time; idle about A$7–8/day (target A$3: missed) |
| **Open** | Grounding rate not sampled on Azure; the 12 h idle check; the submission checklist |
| **Known limits** | Decision-1's dev deployment allows 10 requests a minute, so three local matches lag (Azure: 50); Stream Analytics takes 75–90 s to start after idling; Cancel can take minutes after a long demo; three matches on the shared local model put narratives minutes behind; momentum and fast breaks stay off as claims; no extra time or shoot-outs |

| We chose | Because |
| --- | --- |
| No stubs or hard-coded data on the live path; tunables in the owning service's database and `/dev/` | Prod-shaped; future data must be physically unreachable |
| The feed simulates an external provider (Event Hubs + HLS); one ETL pipeline; every layer keyed by a run-scoped `matchId` | A real provider swaps in at the seam; purge per match |
| Audiences are config-only buckets enabled in `/dev/`; no viewer presence | Predictable generation cost; one pass per bucket |
| SPADL as the action language across the stack (126 stat ids) | One vocabulary for stats, rules, prompts and agents |
| Narratives are storylines grounded in multi-minute trends | On this data minute-to-minute play behaves like independent draws; only half- and match-level control, spells and key events may be claimed |
| Story follows on Microsoft-Decision-1; one follow per viewer | A bounded classifier, not free text, decides when a story moves |
| Exactly three scripted matches from a Start demo picker; seeds recorded on this pipeline; demo control outside the product services | A rich story in seconds, never reconstructed; a release drops the demo |
| Budgets email only; last resort at 90 %, hard stop at 100 % | A daily cap must never stop the live demo |
| Fictional league with original artwork | No third-party marks or real fixtures |

## Build locally

Docker is the only tool you need; no Azure account. The first run downloads several large images (allow 8–12 GB of Docker memory). `ACCEPT_EULA=Y` accepts the Microsoft emulator licences ([local](local/README.md#run-it)).

| Command | Does |
| --- | --- |
| `./dev doctor` · `./dev up` · `./dev test` | Docker preflight; Postgres + Cosmos emulator, then checks |
| `ACCEPT_EULA=Y ./dev up azure` | + Event Hubs, Service Bus, SQL, ETL GraphQL |
| `ACCEPT_EULA=Y ./dev up backend` | The whole product: feed + ETL + engine + API + viewer + demo control, then tests |
| `./dev demo start [fixture…]` · `./dev demo purge` | Purge every match everywhere, then start feed runs at the next whole minute; configuration stays |
| `./dev terraform check` · `./dev down` | Validate and mock-test every Terraform stack in Docker; stop (volumes survive) |

Then press **Start demo** in the [viewer](http://localhost:18020); also the [event filter lab](http://localhost:18020/lab/), [developer config](http://localhost:18020/dev/) and [backend API explorer](http://localhost:18000/docs). Questions and narratives need a local model configured in the ignored `.local/backend-llm.env`; without one the backend reports not ready and refuses questions.

![Local development and Azure validation](local/development.svg)

| Folder | What it does |
| --- | --- |
| [data-generation](data-generation/README.md) | Rendered recordings, plus the **feed**: a simulated external provider (Event Hubs + played HLS) and the demo runs |
| [etl](etl/README.md) | Store events, calculate match statistics and serve them through GraphQL |
| [narrative-engine](narrative-engine/README.md) | Shared match memory, storylines, follow narratives and clips for active audience buckets |
| [user-backend](user-backend/README.md) | Questions, custom stats, replays, follows, clips, cross-game and live delivery for each viewer |
| [frontend](frontend/README.md) | Start demo, viewer, follow view, lab and `/dev/` screen |
| [local](local/README.md) | Local stack, the **contracts** between services, and demo control (start, cancel, skip, seeds) |
| [terraform](terraform/README.md) | Azure infrastructure, `./dev azure`, spend guard, deployment |
| [edge-proxy](edge-proxy/README.md) | Cloudflare Worker serving the demo URL |

Services meet only at the [contracts](local/README.md#contracts), never another service's database: the feed is seen only through Event Hubs and HLS; the backend reads match data only through ETL GraphQL; the backend owns audience definitions and prompts; the engine frames each narrative for its bucket and the backend routes it unchanged; viewer questions never trigger the shared narrative workflow.

## Disclosure

- **Synthetic data.** Every match is a simulation rendered with [Google Research Football](https://github.com/google-research/football) (Apache-2.0). None is a real fixture or Stats Perform data. The league, clubs and players are invented (the fictional Elephant League).
- **AI.** Narratives, answers, clip and replay choices are generated by AI models at run time and labelled synthetic. Locally they use a local model; in Azure, Foundry deployments. Seeded starts replay a story generated earlier on the same pipeline and say so.
- **Artwork.** The league wordmark, club crests and clip sting are original project artwork; the only third-party mark is the Microsoft logo in the "Built with Microsoft Agent Framework" attribution ([provenance](frontend/assets/league/PROVENANCE.md)).

[Agent and coding rules](AGENTS.md) · [Submission](docs/submission.md) · [Target plan (Excalidraw)](master-plan.excalidraw) · [Design board (Excalidraw)](docs/design/plan.excalidraw) · Diagrams: `python3 .github/scripts/render_architecture.py`, `render_development.py`, `render_master_plan.py` (icons identify technologies, not endorsement).
