# User backend

Serves live stat cards, audience narratives, questions, custom stats, replays and story follows. One shared match projection feeds each viewer over WebSocket. Code computes numbers; agents choose what to ask for and explain.

![Questions, calculations and personal delivery](architecture.svg)

## How it works

| Flow | Rule |
| --- | --- |
| Live events | Own Event Hubs consumer group for every match; commit before acknowledging; buffer gaps and recover through ETL |
| Match data | ETL GraphQL only; snapshot = `min(ETL watermark, spadlSeq, received)` |
| Narratives | Receive bucket-framed text over Service Bus unchanged; use engine GraphQL for history |
| Questions | Separate Agent Framework workflow; reuse ETL statistics and bound reads to the viewer's shown sequence |
| Custom stats | Goal → deterministic compiler → validated, bounded rule DSL → code execution; no generated code runs |
| Replays and follows | Agents select evidence; code cuts published HLS. Viewer confirms a follow; identical topics are shared |
| Cross-game | Read each other match at its own position and label its cards; replay results can form one reel |

## Run it

From the repository root, after accepting the [emulator licences](../local/README.md#run-it):

```sh
ACCEPT_EULA=Y ./dev up backend
./dev test backend
```

[API explorer](http://localhost:18000/docs) · [Viewer](http://localhost:18020) · [Configuration](http://localhost:18020/dev/).

Model settings stay in ignored `.local/backend-llm.env`. Without a configured model, readiness fails and model work is refused. Audience definitions, prompts, policy and prices are edited in `/dev/` and survive match purges.

[Tests](tests/) use real Postgres with isolated schemas; doubles replace external services. They cover match isolation, commit failures, restart, gaps, snapshot bounds, questions and clips. [Benchmarks](benchmarks/) are opt-in and do not establish viewer capacity.

## Contracts

[local/README.md Contracts §8–8d](../local/README.md#8-backend-product-api) defines sessions, questions, follows, audiences and replay playback. [Typed models](backend/models/) define inputs and rules; [routes](backend/routes/) translate HTTP; [adapters](backend/adapters/) own external formats.

- The backend owns audience configuration; viewers select enabled buckets, never create generation targets.
- Standard cards use ETL values; custom calculations consume final SPADL actions only (`finalSeq ≤ seq`).
- One session per viewer, profile and match; one follow per viewer per match.
- Purge writes a tombstone before deleting match data; configuration stays.

## Code and decisions

| Code | Why |
| --- | --- |
| [Services](backend/services/) | Use cases and shared match projections; no calculations in routes |
| [Agents and compiler](backend/agents/) | Typed goals, bounded rules, evidence checks and repair |
| [Repositories](backend/repositories/) + [migrations](migrations/) | Own SQL and transaction boundaries |
| [Composition root](backend/app.py) | Inject dependencies once; no fixture mode in runtime code |

## Limits

One process per deployment: projections, fan-out, buffered events and plan conversations are local. More replicas need fenced match ownership, shared delivery and job leases. Per-account quotas and stronger authentication remain production work; the question admission limit is per process.

[Azure workflow and production gaps](../terraform/README.md) · [Deployment status](../README.md#status).
