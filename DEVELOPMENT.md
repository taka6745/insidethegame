# Build locally

> **In short:** Docker is the only tool you need. `ACCEPT_EULA=Y ./dev up backend` runs the whole product locally, including Start demo, seeds, clips and cross-game; `./dev azure up` deploys it.

| | |
| --- | --- |
| **Local** | Every service, Microsoft emulators, SQL Server + DAB, demo control, local model · tested |
| **Seeds** | `.local/seeds/` (20′, HT, 60′, 85′), restored only with `DEMO_SEEDS=1` (set in local compose) |
| **Azure** | [deployment](terraform/docs/deployment.md): Foundry `gpt-6.1-sol` + `Microsoft-Decision-1`, spend guard, edge proxy |

**Start here, people and coding agents.** Docker is the only required tool. No Azure or LocalStack account is needed for this local setup. The first run downloads several large images.

![Local development and Azure validation](local/development.svg)

```sh
./dev doctor
./dev up
```

`up` waits for the integration checks to pass. Use `./dev test` to rerun them later.

For the **whole product**, use:

```sh
ACCEPT_EULA=Y ./dev up backend  # feed + ETL + engine + API + viewer + messaging, then tests
./dev demo start                # purge every match everywhere, then kick off riverton-forgeham next minute
./dev demo start riverton-forgeham redcastle-portalbion skybridge-whitmore   # three matches at once
./dev demo purge                # clear match data everywhere; configuration stays
```

**The demo** runs through demo control instead: press **Start demo** in the viewer (or `POST /demo-api/start {"point": "ht"}`), pick a start point, and the three demo fixtures start, main game first; **Cancel demo** purges them. Mid-match points restore a seed. Record one on the running stack (held runs, then a settle check):

```sh
docker compose -p itg-local exec demo-control python /checks/demo_control.py record 20   # held runs from kickoff
docker compose -p itg-local exec demo-control python /checks/demo_control.py capture 20  # wait until settled, save
```

HT, 60′ and 85′ are recorded as a chain (`record ht --from 20`). See [demo control](local/docs/components/demo-control.md).

[Match viewer](http://localhost:18020) · [Event filter lab](http://localhost:18020/lab/) · [Developer config](http://localhost:18020/dev/) · [Backend API explorer](http://localhost:18000/docs) · [Short walkthrough](user-backend/docs/development.md). Pick a match, then a preset or a typed request. Questions, custom stats and narratives need the [local model](user-backend/docs/components/agents.md); without one the backend reports not ready and refuses questions. Review the [Microsoft emulator licences](local/docs/development.md#3-licences) before starting. No Azure login is needed. `./dev test backend` reruns isolated backend tests and real broker probes without touching running matches.

For the emulators, SQL and ETL GraphQL alone (no feed or services), first review the [Microsoft licence links](local/docs/development.md#3-licences), then:

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

## Work independently

Follow [development practices](DEVELOPMENT-PRACTICES.md): views call services; services use models, repositories and adapters. Keep logic, migrations and application tests inside the owning service. Shared wiring and dependency checks live in [local/](local/README.md). Azure resource definitions live in each service's `infra/`; [terraform/](terraform/README.md) holds the backend, demo control, frontend, seeds share, Key Vault and the `questions` deployment, plus the spend guard (`terraform/guard`).

Use the documented API/message boundary, never another service's database. Start with fixtures when another service isn't ready. Label fixture output; don't present it as a real model or pipeline result. Agree changes to [integration contracts](local/contracts/README.md) before changing producers and consumers.

```sh
./dev terraform check
```

This validates and mock-tests Terraform in Docker, with no accounts or cloud deployment. **Stream Analytics belongs to the ETL service.** Identity, networking and scale gaps: [terraform decisions §2](terraform/docs/decisions.md#2-before-a-production-release).

## Recorded match demo

Flow: [local architecture §1](local/docs/architecture.md#1-flow). The checked-in recordings are fictional Elephant League simulations (Riverton Rovers–Forgeham United, Redcastle Town–Port Albion, Skybridge City–Whitmore Wanderers). Large footage stays ignored; `./dev` mounts each `.local/grf-demo-{fixture}-90/hls/` that exists into the feed only, and a fixture without media plays without video ([generation](data-generation/docs/components/grf-demo.md)). Nothing reaches a viewer before it has been streamed: only the feed holds recordings and media. Replays: [backend services](user-backend/docs/components/services.md). Logs: `./dev logs feed`, `./dev logs etl-stream`, `./dev logs narrative-live`.
