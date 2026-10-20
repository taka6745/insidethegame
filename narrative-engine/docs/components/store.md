# Store

> **In short:** where the engine keeps its state: checkpoints, context blocks and narratives. `cosmos.py` uses Cosmos DB in Azure; `memory.py` keeps the same data in dictionaries for tests and local runs. A shared contract test runs against both.

| | |
| --- | --- |
| **Status** | Implemented · tested · deployed (Cosmos DB serverless) |
| **Code** | [`narrative_engine/store/`](../../narrative_engine/store/): `__init__.py` (interface), `cosmos.py`, `memory.py` |
| **Auth** | Entra ID only (`DefaultAzureCredential`: `az login` locally, managed identity in Azure) |
| **Tests** | `test_store_contract.py` (memory always; real Cosmos when `COSMOS_ENDPOINT` is set) |

## 1. Interface (`Store`)

*In short: nine async methods, all scoped to one match.*

| Method | Purpose |
| --- | --- |
| `get_checkpoint` / `save_checkpoint` | The match's progress document |
| `put_block` | Save a context block |
| `supersede(block, input_ids)` | Save a compressed block and mark its inputs replaced |
| `active_blocks` | Non-superseded blocks in match order |
| `add_narrative` | Save a narrative |
| `narratives(matchId, userType)` | A bucket's narratives in `seq` order |
| `narratives_after(matchId, userType, afterSeq, limit)` | One page for the history API |
| `narrative_for_step(matchId, userType, stepId)` | Detects a step already written (retries republish it) |
| `live_match_ids` | Matches to resume after a restart |

## 2. Cosmos DB (`cosmos.py`)

*In short: database `narrative`, three containers partitioned by `/matchId`.*

| Container | Documents |
| --- | --- |
| `checkpoints` | One per match ([fields](../architecture.md#41-checkpoints-one-document-per-match)) |
| `contextBlocks` | Every block, superseded ones included |
| `narratives` | Every narrative |

Every read and write stays in one partition except `live_match_ids`, a small cross-partition query on checkpoints. `all_blocks` returns superseded blocks too, for the report.

## 3. In memory (`memory.py`)

*In short: dictionaries with the same behaviour, so tests and local runs need no Azure.*

There is no Cosmos emulator in the setup; the contract test is what keeps the two stores equivalent.
