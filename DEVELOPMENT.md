# Build locally

> **In short:** Docker is the only tool you need. `ACCEPT_EULA=Y ./dev up backend` runs the whole product locally, including Start demo, seeds, clips and cross-game; `./dev azure up` deploys it (applied 22 Oct, acceptance pending).

| | |
| --- | --- |
| **Local** | Every service, Microsoft emulators, SQL Server + DAB, demo control, local model · tested (PLAN.md §10.7) |
| **Seeds** | `.local/seeds/` (20′, HT, 60′, 85′), restored only with `DEMO_SEEDS=1` (set in local compose) |
| **Azure** | [runbook](terraform/runbook.md): Foundry `gpt-6.1-sol` + `Microsoft-Decision-1`, spend guard, edge proxy |

**Start here, people and coding agents.** Docker is the only required tool. No Azure or LocalStack account is needed for this local setup. The first run downloads several large images.

![Local development and Azure validation](local/development.svg)

```sh
./dev doctor
./dev up
```

`up` waits for the integration checks to pass. Use `./dev test` to rerun them later.

For the **runnable user-backend harness**, use:

```sh
ACCEPT_EULA=Y ./dev up backend  # feed + ETL + engine + API + viewer + messaging, then tests
./dev demo start                # purge every match everywhere, then kick off chelsea-united next minute
./dev demo start chelsea-united arsenal-liverpool mancity-tottenham   # three matches at once
./dev demo purge                # clear match data everywhere; configuration stays
```

**The judge demo** runs through demo control instead: press **Start demo** in the viewer (or `POST /demo-api/start {"point": "ht"}`), pick a start point, and the three demo fixtures start, main game first; **Cancel demo** purges them. Mid-match points restore a seed. Record one on the running stack (held runs, then a settle check):

```sh
docker compose -p itg-local exec demo-control python /checks/demo_control.py record 20   # held runs from kickoff
docker compose -p itg-local exec demo-control python /checks/demo_control.py capture 20  # wait until settled, save
```

HT, 60′ and 85′ are recorded as a chain (`record ht --from 20`). See [local/README.md](local/README.md#demo-control-and-seeds).

[Match viewer](http://localhost:18020) · [Event filter lab](http://localhost:18020/lab/) · [Developer config](http://localhost:18020/dev/) · [Backend API explorer](http://localhost:18000/docs) · [Short walkthrough](user-backend/docs/development.md). Pick a match, then a preset or a typed request. Questions, custom stats and narratives need the [local model](user-backend/docs/components/agents.md); without one the backend reports not ready and refuses questions. Review the [Microsoft emulator licences](local/README.md#licences) before starting. No Azure login is needed. `./dev test backend` reruns isolated backend tests and real broker probes without touching running matches.

For the emulators, SQL and ETL GraphQL alone (no feed or services), first review the [Microsoft licence links](local/README.md#licences), then:

```sh
ACCEPT_EULA=Y ./dev up azure
```

`./dev status`, `./dev logs servicebus` and `./dev down` manage only this project's containers. SQL/Postgres volumes survive `down`; emulator messages are disposable. Commands work from the repo root on macOS/Linux, or WSL on Windows.

## Pick your service

| Work on | Start with | First useful result |
| --- | --- | --- |
| Feed and recordings | [data-generation guide](data-generation/docs/development.md) | Run a recorded match live into Event Hubs and HLS. |
| Match data | [ETL guide](etl/docs/development.md) | Events → stored history → GraphQL. |
| Shared narratives | [narrative guide](narrative-engine/docs/development.md) | One minute of context → stored bucket narrative. |
| Viewer experience | [backend guide](user-backend/docs/development.md) | Profile → bucket → current stats and narrative backlog. |
| UI | [frontend guide](frontend/docs/development.md) | Match picker, live match, cards and chat. |

The stack includes a **working match viewer, structured-filter lab and developer config screen**. Live insights come from the narrative engine (`narrative-live`), fed by a local stand-in for the Stream Analytics job; stat cards and questions read its GraphQL (`executeStatsAtSeq`). The whole stack deploys to Azure with `./dev azure up` (applied 22 Oct for the Azure test; [runbook](terraform/runbook.md), [ETL docs](etl/docs/README.md), [narrative docs](narrative-engine/docs/README.md)); there the real Stream Analytics job replaces the local stand-in. Custom rules are typed rules, never generated Python.

## Work independently

Follow [development practices](DEVELOPMENT-PRACTICES.md): views call services; services use models, repositories and adapters. Keep logic, migrations and application tests inside the owning service. Shared wiring and dependency checks live in [local/](local/README.md). Azure resource definitions live in each service's `infra/`; [terraform/](terraform/README.md) holds only the shared user-backend scaffold.

Use the documented API/message boundary, never another service's database. Start with fixtures when another service isn't ready. Label fixture output; don't present it as a real model or pipeline result. Agree changes to [integration contracts](local/contracts.md) before changing producers and consumers.

```sh
./dev terraform check
```

This validates and mock-tests Terraform in Docker, with no accounts or cloud deployment. Real Azure integration remains a separate check: **Stream Analytics belongs to the ETL service**, Foundry needs an actual model endpoint, and managed identity/networking/scale need Azure validation.


## Recorded match demo

```text
feed (recordings, N runs at once) → Event Hubs match-events (MA1, MA3, POS, MatchEvent v2; key matchId)
  │                                 └→ played HLS → nginx /media/hls/{matchId}/
  ├→ backend event consumer ─────────────────────────────── clock, ticker, gap recovery
  └→ etl-stream (Stream Analytics stand-in + SPADL) → SQL + etl-dab GraphQL :15001 ── stat cards, custom stats, questions
       └→ Service Bus match-notifications / narrative-live
            → narrative engine ← active audience targets + prompts ← backend ← /dev/ config
            → Service Bus narratives → backend → viewer (released at its video clock)
```

| Piece | Implemented | Tested locally | Azure (`./dev azure up`, applied 22 Oct, acceptance pending) |
| --- | --- | --- | --- |
| Feed (`data-generation/feed/`, simulated provider) | Yes | Unit tests, three concurrent runs, held/resumed seed runs | Deployed (internal ingress) |
| Backend, viewer, lab, `/dev/` screen | Yes | Unit tests, `./dev test backend`, headless flows, three concurrent runs | Deployed (frontend public behind the edge proxy, backend internal) |
| Demo control (`local/demo_control.py`) | Yes | Unit tests, seeded and kickoff starts, cancel | Deployed (internal; `/demo-api/` via nginx); seeds on Azure Files |
| `etl-stream` + SQL + DAB (`etl/local_stream/`) | Yes | Unit + SQL tests, `broker_check.py`, three concurrent runs | Replaced by the real Stream Analytics job (started and stopped by the spend guard); DAB and purge API deployed (internal) |
| Narrative engine (`narrative-live`, Cosmos emulator) | Yes | Unit tests, three concurrent runs | Deployed (internal ingress; Decision-1 applied, `gpt-6.1-sol` rollout pending) |

Each feed run is its own match: `{fixture}-{first 8 hex of run id}`, and several run at once. The engine runs one orchestrator per match, writes only for the **audience buckets enabled** in the backend's per-fixture configuration (`/dev/`) and uses the **active prompt versions** stored in the backend; model calls share one semaphore across matches. The backend pushes each narrative to that match's viewers when it arrives; the viewer shows it once its video reaches the narrative's clock. The engine and backend use the local model from the ignored `.local/backend-llm.env`.

The checked-in recordings are rendered real-club simulations (Chelsea–United, Arsenal–Liverpool, Man City–Tottenham). Large footage remains ignored. `./dev` mounts each `.local/grf-demo-{fixture}-90/hls/` that exists into the feed only; a fixture without media plays without video. See [generation instructions](data-generation/docs/components/grf-demo.md). Playback is real time (90 minutes plus stoppage) as live HLS; viewers can ask in chat for replay clips ([replay](user-backend/docs/design/replay-plan.md)), with live kept as picture-in-picture.

**Live only, per match.** Nothing reaches a viewer before it has been streamed: only the feed (a simulated external provider) holds recordings and media; no API serves them, future events or unplayed HLS segments, and there is no MP4. Questions read recaps from the engine's history GraphQL (`contextBlocks`) and facts from ETL GraphQL. `./dev demo start` first purges every match from every owner (`POST /admin/matches/purge`: feed, `etl-stream`, narrative engine, backend), then starts the runs. Account profiles, audience templates (with their enabled buckets), prompt versions, presentation config and prices are configuration and stay. Logs: `./dev logs feed`, `./dev logs etl-stream`, `./dev logs narrative-live`.
