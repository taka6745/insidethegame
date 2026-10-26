# Narrative engine

Turns match facts into evolving stories with Microsoft Agent Framework on Azure AI Foundry. Memory and analysis are shared per match; the author writes for each enabled audience. Viewer questions stay in the backend.

![Shared match context becomes audience narratives](architecture.svg)

## How it runs

| Step | Purpose |
| --- | --- |
| Summarise each closed minute | Keep recent play in detail; compress older context |
| Analyse every five minutes and at period ends | Find trends supported by ETL numbers; open, develop or resolve storylines |
| Author on key events, story turns or quiet intervals | Advance one shared story, framed for each audience |
| Check with Microsoft-Decision-1 | Validate claims, detect followed-story changes and select clip moments |

One repair attempt, then drop unsupported text. Clips are selected independently; the backend cuts the video. Checkpoint messages before acknowledging them, then work in the background. Every read stays within the step's recorded horizon; restarts resume from Cosmos DB.

## Context compression

Within each half: **11 minute summaries → oldest five become a block; four blocks → oldest two merge into earlier context**. At period end, collapse that period into one block. No gaps, overlaps or blocks spanning half time. [Rules](narrative_engine/context/compression.py) · [Tests](tests/test_compression.py).

Shared context comes first in the author prompt, audience framing last, to allow prefix caching. [Versioned prompts](narrative_engine/agents/prompts/); [original examples](docs/design/example-prompts/) remain unchanged.

## Run it

Use `ACCEPT_EULA=Y ./dev up backend` after accepting the [emulator licences](../local/README.md#run-it). Logs: `./dev logs narrative-live`; history: [localhost:18012/graphql](http://localhost:18012/graphql).

```sh
cd narrative-engine
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

Cosmos tests need `COSMOS_ENDPOINT`; live ETL tests need the stack. [Tests](tests/) cover grounding, compression, retries, restart, concurrent matches and snapshot bounds. [Dev tools](devtools/) provide offline replay and run reports.

## Contracts

| Boundary | Contract |
| --- | --- |
| Inputs | ETL GraphQL + `match-notifications`; backend audience targets, prompts, policy, model roles and follow topics |
| Live output | Service Bus `narratives`: bucket and follow narratives, `FollowClip`, `MomentClip`; deduplicate by `id`, show only once the viewer reaches `eventSeq` |
| History | Read-only `/graphql`, paged by match, bucket and sequence |
| Admin | Tombstone before purge; stop match workers and remove owned match state |

[Message models](narrative_engine/core/models.py) · [History API](narrative_engine/api.py) · [local/README.md Contracts §8–8b](../local/README.md#8-backend-product-api). The backend owns audience definitions; only enabled buckets generate, with no fallback list. Follow decisions share topics without exposing viewer text in shared state.

## Decisions and limits

- One worker per match, one global model gate: overload queues work rather than skipping it.
- One replica; extra time and shoot-outs are unsupported. Grounding quality still needs sampling; model latency limits throughput.
- Cosmos holds memory and checkpoints; Service Bus carries live output; GraphQL fills history gaps.

[Azure workflow and production gaps](../terraform/README.md) · [Deployment status](../README.md#status).
