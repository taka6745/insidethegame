# Development

> **In short:** run the backend in the shared Docker stack (`./dev up backend`), configure a model in an ignored env file, and test with `./dev test backend` or `pytest` against any Postgres. Test doubles for the feed, ETL GraphQL and the engine live in `tests/harness.py`; nothing on the live path is a stand-in.

| | |
| --- | --- |
| **Status** | Implemented · tested against real Postgres and contract doubles · run in the local stack |
| **Start** | `ACCEPT_EULA=Y ./dev up backend`, then `./dev demo start [fixture…]` |
| **Ports** | API `localhost:18000` ([explorer](http://localhost:18000/docs)); viewer, lab and `/dev/` on `localhost:18020` |
| **Model** | `.local/backend-llm.env` (`LOCAL_LLM_*`, mode `600`, never committed or printed) |
| **Contracts** | [local/contracts.md](../../local/contracts.md) §1–8 |

## 1. Run it

*In short: the shared stack, from kickoff.*

```sh
ACCEPT_EULA=Y ./dev up backend   # Microsoft emulator licences need each developer's acceptance
./dev demo start [fixture…]      # every owner purges, then the feed starts runs at the next minute (00:00)
./dev test backend               # isolated pytest + broker probes, without touching running matches
```

The image has two targets: `runtime` (backend + migrations, no tests or fixtures) and `test` (adds `tests/`, `benchmarks/`, `fixtures/`). Run one backend process per deployment ([architecture §6](architecture.md#6-scaling-boundary)).

## 2. Configuration

*In short: environment for wiring; `/dev/` tables for tunables.*

| Variable | Use |
| --- | --- |
| `ACCOUNTS_DATABASE_URL`, `MATCH_APP_DATABASE_URL`, `POSTGRES_POOL_SIZE` | Postgres (required; pool default 10) |
| `ETL_GRAPHQL_URL`, `NARRATIVE_GRAPHQL_URL` | ETL DAB and engine GraphQL (required); their `/health` feed `/dev/pipeline` |
| `MATCH_EVENTHUB_CONNECTION_STRING`, `_NAME`, `_CONSUMER_GROUP`, `_START` | `match-events`, group `user-backend`, `latest` or `earliest` |
| `NARRATIVE_SERVICEBUS_CONNECTION_STRING`, `_TOPIC`, `_SUBSCRIPTION` | `narratives` / `user-backend` |
| `FEED_HLS_BASE`, `PUBLIC_HLS_BASE` | Feed playlist origin over HTTP; browser path (`/media/hls/`) |
| `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_API_KEY`, `LOCAL_LLM_TIMEOUT_SECONDS` | Model endpoint; without the first two the service is not ready |
| `AGENT_*`, `QUESTION_*`, `FILTER_MAX_CALCULATIONS` | Agent and question limits ([agents §5](components/agents.md#5-limits-and-configuration)) |
| `ENABLE_DEV_FEED`, `ENABLE_FILTER_LAB` | Mount `/dev/*` and `/lab/*` (local only) |
| `DEMO_SEEDS` | `1` mounts the demo seed routes (local compose, judge build); unset in a production release |
| `DECISION_*` | Microsoft-Decision-1 for the follow offer (`.local/decision.env`, never printed); without it the question model answers |

Tunables (card presentation, replay timing and playback, key-moment ranks and feed, answer prices, gap timeout, story follows and clips, storyline policy, cross-match, follow offer), audience templates, prompts and demo profiles are edited at [localhost:18020/dev/](http://localhost:18020/dev/) and survive purges.

## 3. Local stand-ins

*In short: Microsoft emulators locally; real Azure services in the cloud.*

| Azure service | Local |
| --- | --- |
| Event Hubs, Service Bus | Microsoft emulators |
| Azure SQL + Data API builder (ETL) | SQL Server container + DAB |
| Azure Database for PostgreSQL | `postgres` container (`accounts`, `matchapp`) |
| Azure AI Foundry model | A configured development endpoint |

## 4. Tests

*In short: every behaviour against real Postgres, one throwaway schema per test.*

```sh
cd user-backend
ACCOUNTS_DATABASE_URL=postgresql://… MATCH_APP_DATABASE_URL=postgresql://… pytest -q
```

`tests/harness.py` plays the feed (messages through the real parser) and ETL DAB (an `httpx` transport answering the contract's queries, including `spadlActions` and MA3 `rawEvents` from `benchmarks/doubles/spadl.py`, from committed events); agent doubles live in `benchmarks/doubles/`. No model, broker or cloud account is needed.

| Check | Evidence |
| --- | --- |
| Isolation | Two live matches never cite each other's cards, narratives, answers or replays (`test_multi_match.py`) |
| Sessions | One profile on two matches; a token is `404` under another match; takeover closes the old socket (`4001`); per-match session locks |
| Restart | Every match rebuilt from received events and saved calculations; custom values recounted from SPADL actions, versions only move forward |
| No future data | Snapshot = min(ETL watermark, spadlSeq, received); only actions with `finalSeq ≤ seq`; answers never cite anything after the viewer's `seq` |
| SPADL | DSL predicates, zones, x/y, shot outcomes, recorded body parts; contract file freshness; migrations `020`/`021` (`test_spadl_contract.py`, `test_spadl_migrations.py`) |
| Gaps | Buffered out-of-order events; recovery from `canonicalEvents` or a recorded skip; checkpoint held while open; `/health` and `/dev/pipeline` report it |
| Purge | Tombstone first; sockets close `4404`; late messages never revive a match; configuration stays |
| Product | Cards from configuration, durable pins, shared projection work |
| Audiences | Only enabled buckets are targets; the viewer chooses among them; template edits are revision-checked |
| Config and profiles | ETag/revision reads and writes for every table, prices and demo profiles |
| Questions | Admission limit, takeover/purge races, timeouts, evidence checks, clarification, replay pages |
| No model | `/ready` 503; questions and lab plans refused |
| Runtime boundary | No backend module imports recordings, fixtures or doubles |
| Clips | Follow and key-event clips reach the right viewers, never past the snapshot (`test_key_event_clips_reach_every_insights_viewer_of_their_bucket`, `test_a_key_event_clip_never_passes_the_snapshot`) |
| Demo seeds | Export, refusals, restore and adopt; routes absent without `DEMO_SEEDS` (`test_seed_routes_exist_only_with_the_demo_setting`) |
| Domain | Filter engine (with differential property tests), time index, composites, agent contracts, data reference |

`./dev test backend` also runs `local/backend_broker_check.py`: a probe match through the real Event Hubs emulator into an isolated registry, duplicate and restore checks, then a purge from every owner. Not established here: multi-replica delivery, production brokers, browser playback or general model accuracy.

## 5. SPADL reference

*In short: regenerate the backend's copy of the ETL SPADL contract after it changes.*

```sh
cd user-backend && python -m devtools.spadl_reference   # writes backend/contracts/spadl-reference.json
```

## 6. Golden sets

*In short: scripted decisions in pytest; the live model on demand.*

`python -m benchmarks.question_inprocess --agent fixture` and `python -m benchmarks.replay_eval --agent fixture` (both also in pytest); use `--env-file ../.local/backend-llm.env` for the local model. See [benchmarks](components/benchmarks.md).
