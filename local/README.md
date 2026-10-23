# Local integration

> **In short:** one Docker Compose project (`itg-local`) runs every service, the Microsoft emulators and the demo operator; `./dev` starts and checks it. The stream worker, emulators and local model are never deployed; the feed, `etl-stream`'s purge and SPADL roles and demo control are. [Docs](docs/README.md) · [Contracts](contracts/README.md).

| | |
| --- | --- |
| **Status** | Tested (every service on one stack, three concurrent matches, seeded starts) |
| **Demo** | `demo-control` behind `/demo-api/`; seeds in `.local/seeds/`; `DEMO_SEEDS=1` on feed, ETL, engine, backend |
| **Model** | Local model from the ignored `.local/backend-llm.env`; Decision-1 dev deployment from `.local/decision.env` (never print either) |

Run from the repo root using [`../dev`](../dev). Review the [licences](docs/development.md#3-licences) first; no account is needed.

```sh
./dev doctor                    # Docker preflight
./dev up                        # Postgres + Cosmos, then checks
ACCEPT_EULA=Y ./dev up azure    # + Event Hubs, Service Bus, SQL, ETL GraphQL (DAB)
ACCEPT_EULA=Y ./dev up backend  # the whole product, then backend tests and pipeline probes
./dev demo start [fixture…]     # purge every match, then start feed runs at the next whole minute
./dev down                      # stop; keep SQL/Postgres volumes
```

Viewer `http://localhost:18020/` (lab `/lab/`, developer `/dev/`), backend `http://localhost:18000/docs`, ETL GraphQL `http://localhost:15001/graphql`. Only loopback ports are published; don't expose this unauthenticated stack to a network.
