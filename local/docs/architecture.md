# Architecture

> **In short:** one Compose project; services meet only at the [contracts](../contracts/README.md): Event Hubs, Service Bus, GraphQL and HTTP. The feed is an external provider with its own database and network.

| | |
| --- | --- |
| **Project** | `itg-local` (`ITG_PROJECT_NAME`); every host port is an `ITG_*_PORT` variable |
| **Networks** | Default (our services), `provider` (feed + `feed-postgres` only) |
| **Media** | One read-only root, `ITG_MEDIA_ROOT` (default `.local/media`), mounted into the feed only |

## 1. Flow

*In short: the feed sends events and HLS; everything else reads through the ETL.*

```text
feed ─ MA1, MA3, POS, MatchEvent v2 → Event Hubs ─┬→ backend (received events, custom rules)
  └─ played HLS ← nginx /media/hls/{matchId}/      └→ etl-stream → SQL + etl-dab GraphQL → backend, engine
                                                         └→ Service Bus match-notifications (narrative-live)
                         backend ← Service Bus narratives ← narrative engine (audience targets + prompts from backend)
                            ↓
                          viewer ─ /demo-api/ → demo control → feed, ETL, engine, backend
```

`etl-stream` ([etl/local_stream](../../etl/docs/components/local-stream.md)) is a Python stand-in for the Stream Analytics job; ETL GraphQL (`etl-dab`) is the backend's only match-data read path. Event Hubs consumers start at the present (or their checkpoint), never the retained backlog; Service Bus subscriptions are shared, so consumers drop messages of purged matches. Locally the engine reads `match-notifications` through `narrative-live`.

## 2. What runs

*In short: services, emulators and their host addresses.*

| Dependency | Local implementation | Host address |
| --- | --- | --- |
| User databases | PostgreSQL 16, `accounts` + `matchapp` | `localhost:15432` |
| Cosmos | Microsoft Cosmos vNext emulator (UI on `11234`) | `http://localhost:18081` |
| Match events (`backend` + `azure`) | Microsoft Event Hubs emulator | AMQP `localhost:15672` |
| Notifications and narratives (`backend` + `azure`) | Microsoft Service Bus emulator | AMQP `localhost:15673` |
| Service Bus storage + ETL SQL (`backend` + `azure`) | SQL Server 2022 Developer | `localhost:11433` |
| ETL pipeline | SQL `insidethegame` + Data API builder 2.1.5 + `etl-stream` | `http://localhost:15001/graphql` |
| Narrative engine | `narrative-live`, Cosmos emulator state, local model | `http://localhost:18012/graphql` |
| User backend | FastAPI + WebSocket | `http://localhost:18000/docs` |
| Feed | Simulated provider: recordings → Event Hubs + played HLS; dev-only admin API | `http://localhost:18030` |
| Match viewer | nginx; HLS proxied from the feed; `/lab/`, `/dev/`, `/demo-api/` | `http://localhost:18020/` |
| Demo control | [`demo_control.py`](../demo_control.py) `serve`; seeds `.local/seeds` → `/seeds` | `/demo-api/` only |

Inside Docker use service names and native ports: `postgres:5432`, `feed:8000`, `etl-stream:8000`, `etl-dab:5000`, `narrative-live:8000`, `backend:8000`, `cosmos:8081`, `eventhubs:5672`, `servicebus:5672`, `sql:1433`.

## 3. Media

*In short: only played segments leave the feed.*

`./dev` hard-links each packaged `.local/grf-demo-{fixture}-90/hls/` into `.local/media/{fixture}/hls/` (no copy; delete it to relink after regenerating), so nothing else in `.local/` is mounted. A fixture without media plays with `video: false`. The feed publishes only played segments at `/hls/{matchId}/live.m3u8`; nginx proxies `/media/hls/{matchId}/` to it and serves nothing else under `/media/`.
