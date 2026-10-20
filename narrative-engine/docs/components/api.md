# API

> **In short:** a read-only GraphQL API for narrative history, served by the engine itself. The user backend uses it to show a bucket's backlog when a viewer joins and to fill gaps after a reconnect; live narratives arrive on Service Bus.

| | |
| --- | --- |
| **Status** | Implemented · tested · deployed |
| **Code** | [`narrative_engine/api.py`](../../narrative_engine/api.py) |
| **Library** | Strawberry GraphQL (ASGI) on uvicorn; no web framework |
| **URL (dev)** | `https://itg-narrative-dev-engine.mangosmoke-bbf503ab.australiaeast.azurecontainerapps.io/graphql` (anonymous read) |
| **Contract** | [contracts/README.md](../../contracts/README.md#output-1-graphql-narrative-history-read-only) |
| **Tests** | `test_api.py` |

## 1. Queries

*In short: one paged list and one status query.*

| Query | Returns |
| --- | --- |
| `narratives(matchId, userType, afterSeq = 0, first = 50)` | The bucket's narratives with `seq > afterSeq`, oldest first, with `hasNextPage` and `endCursor` |
| `matchState(matchId)` | `status`, `lastSummarised`, `activeUserTypes` |

Invalid buckets and `first` outside 1–200 are GraphQL errors.

## 2. Why GraphQL inside the engine

*In short: same style as the ETL's API, testable without Azure, and it can answer questions Cosmos alone can't.*

- Consumers already use GraphQL for the ETL, so the user backend has one query style.
- It runs in-process over either store, so tests and local runs need no Cosmos emulator.
- `activeUserTypes` is computed from presence and staleness rules, which Data API builder over Cosmos could not express.

## 3. Running it locally

*In short: serve a local run's output, or serve live during a replay.*

```sh
python -m narrative_engine.api .local/narratives.jsonl --port 8000
python -m narrative_engine.devtools.local <notifications.jsonl> --serve 8000
```

Then open `http://localhost:8000/graphql` for the GraphiQL explorer.
