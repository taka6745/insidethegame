# Overview

> **In short:** `./dev` runs the whole product on one machine: the feed (a simulated provider), the ETL stand-in, the narrative engine, the backend, the viewer and demo control, on Microsoft emulators. Tested; local only, except demo control, which is also deployed on Azure.

| | |
| --- | --- |
| **Status** | Tested: every service on one stack, three concurrent matches, kickoff and seeded starts, follows, clips, cross-game |
| **Profiles** | base (Postgres, Cosmos), `azure` (+ messaging, SQL, DAB), `backend` (+ every service) |
| **Not deployed** | `etl-stream` (Stream Analytics stand-in), emulators, local model |

## 1. Profiles

*In short: three levels, each started and checked by `./dev up`.*

| Command | Adds | Checks |
| --- | --- | --- |
| `./dev up` | PostgreSQL (`accounts`, `matchapp`), Cosmos emulator | Postgres read/write, Cosmos document round trip |
| `ACCEPT_EULA=Y ./dev up azure` | Event Hubs, Service Bus, SQL Server, ETL GraphQL (DAB) | Read-only ETL GraphQL, Event Hubs and Service Bus send/receive |
| `ACCEPT_EULA=Y ./dev up backend` | Feed, `etl-stream`, narrative engine, backend, viewer, demo control | Backend tests plus non-destructive pipeline probes ([checks](components/checks.md)) |

The `azure` profile has no stream processor, so nothing writes match data; matches come from the backend profile's feed (`./dev demo start` or Start demo).

## 2. Demo and purge

*In short: start and purge from the CLI or the viewer.*

`./dev demo start [fixture…]` purges every match from every owner (feed, ETL, engine, backend), then starts one feed run per fixture (default `riverton-forgeham`) at the next whole minute, from 00:00; `./dev demo purge` only purges. Configuration stays: profiles, audience templates, prompts, backend config, `statDefinitions` and the recordings catalogue. The viewer's Start demo runs through [demo control](components/demo-control.md).
