# API

> **In short:** a read-only GraphQL API for narrative history, served by the engine itself. The user backend uses it to show a bucket's backlog when a viewer joins and to fill gaps after a reconnect; live narratives arrive on Service Bus.

| | |
| --- | --- |
| **Status** | Implemented · tested |
| **Code** | [`narrative_engine/api.py`](../../narrative_engine/api.py) |
| **Library** | Strawberry GraphQL (ASGI) on uvicorn; no web framework |
| **URL (Azure)** | `https://itg-narrative-dev-engine.internal.<environment domain>/graphql`: internal ingress, anonymous read inside the environment |
| **Contract** | [contracts/README.md](../../contracts/README.md#output-1-graphql-narrative-history-read-only) |
| **Tests** | `test_api.py` |

## 1. Queries

*In short: one paged list and one status query.*

| Query | Returns |
| --- | --- |
| `narratives(matchId, userType, afterSeq = 0, first = 50)` | The bucket's narratives with `seq > afterSeq`, oldest first, with `hasNextPage` and `endCursor` |
| `subscriptionNarratives(matchId, topicId, userType, afterSeq = 0, first = 50)` | One followed topic's narratives for one bucket, paged like `narratives`, with `topicId` and `decision` |
| `matchState(matchId)` | `status`, `lastSummarised`, `activeUserTypes` |
| `storylines(matchId)` | The match's storylines (label, team, status, salience, beats, linked `keyEventIds`), in the order they opened |
| `contextBlocks(matchId, includeSuperseded = true)` | Neutral context summaries (`level` 0 minute, 1 five-minute, 2 earlier/period; `tier` `minute`, `five-minute`, `twenty-minute`, `half`), oldest first; `false` returns only the active context |

Narratives carry `eventSeq`, the canonical seq of the data they were written from, and `analysisId`/`storylineIds` (the storyline they advance). The service also answers `GET /health` and `POST /admin/matches/purge` (`{"match_id"}` or `{"all": true}`, [contract](../../../local/contracts/README.md#5-purge)) beside `/graphql` (`service.service_app`). On Azure the ingress is internal and the purge also needs `Authorization: Bearer $ADMIN_TOKEN`; the frontend's `/purge-api/engine` adds it.

Invalid buckets or topic ids and `first` outside 1–200 are GraphQL errors.

## 2. Why GraphQL inside the engine

*In short: same style as the ETL's API, testable without Azure, and it can answer questions Cosmos alone can't.*

- Consumers already use GraphQL for the ETL, so the user backend has one query style.
- It runs in-process over either store, so unit tests and devtools need no Cosmos.
- `activeUserTypes` is the last audience targets read from the user backend.

## 3. Running it locally

*In short: serve a local run's output, or serve live during a replay.*

```sh
python -m narrative_engine.api .local/narratives.jsonl --port 8000
python -m devtools.local <notifications.jsonl> --serve 8000
```

Then open `http://localhost:8000/graphql` for the GraphiQL explorer.
