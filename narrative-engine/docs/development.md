# Development

> **In short:** a plain Python virtual environment, no Docker needed. Each Azure dependency has a local stand-in (in-memory store, fixture files, JSONL transport, fake agents), so the whole engine runs offline; the same code then points at Azure dev resources one piece at a time.

| | |
| --- | --- |
| **Needs** | Python 3.11; Azure CLI and Terraform only for Azure work; Docker only to build the image |
| **Settings** | Ignored `narrative-engine/.env` (never committed) |
| **Tests** | `pytest tests` (66 pass, 2 skip without Azure) |

## 1. Setup

*In short: one virtual environment.*

```sh
cd narrative-engine
py -3.11 -m venv .venv                       # Windows; python3.11 elsewhere
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m pytest tests
```

## 2. Local stand-ins

*In short: every Azure service has an offline replacement, swapped in by settings.*

| Azure piece | Local stand-in | Switch |
| --- | --- | --- |
| Cosmos DB | `MemoryStore` (dictionaries) | `COSMOS_ENDPOINT` unset |
| ETL GraphQL | `FixtureMatchData` over `tests/fixtures/` (synthetic match `itg-syn-0001`), or the ETL's local DAB in Docker on :5000 | `--data fixture\|graphql` |
| Service Bus in | ETL notifications JSONL (`etl/.local/notifications.jsonl` from the ETL's `load-local`, or `tests/fixtures/itg-syn-0001-notifications.jsonl`) | `devtools.local` |
| Service Bus out | `.local/narratives.jsonl` | `devtools.local --out` |
| Foundry | `FakeAgents`, or any OpenAI-compatible API in `.env` | `--agents fake\|llm` |

The `MemoryStore` and Cosmos store share a contract test, and a fake-agent run over the fixture matches a run against the Azure dev DAB, so passing locally means the same behaviour in Azure.

## 3. Common runs

*In short: from fastest and most offline to closest to production.*

```sh
# 1. Whole match, fake agents, offline (seconds)
.venv/Scripts/python -m narrative_engine.devtools.local tests/fixtures/itg-syn-0001-notifications.jsonl

# 2. Real models, two buckets (about 5 minutes on Foundry)
.venv/Scripts/python -m narrative_engine.devtools.local tests/fixtures/itg-syn-0001-notifications.jsonl \
  --agents llm --presence '{"neutral:casual": 1, "home:analyst": 1}'

# 3. Real models and the Azure dev ETL data
ETL_GRAPHQL_URL=<dev graphql url> .venv/Scripts/python -m narrative_engine.devtools.local \
  tests/fixtures/itg-syn-0001-notifications.jsonl --data graphql --match-id itg-syn-0001-cloud4 --agents llm

# 4. The full service on your machine against Azure dev (Service Bus, Cosmos DB)
.venv/Scripts/python -m narrative_engine.devtools.azure env      # settings into .env
MATCH_IDS=<matchId> .venv/Scripts/python -m narrative_engine.service
```

Look at the results with the history API (`python -m narrative_engine.api .local/narratives.jsonl`) or, for Cosmos data, the HTML report (`devtools.azure report --match-id X`).

## 4. Tests

*In short: fast unit and integration tests; Azure-backed tests skip when Azure is not configured.*

| File | Covers |
| --- | --- |
| `test_models.py` | Clock, labels, message parsing |
| `test_compression.py` | Compression rules against the design's worked example |
| `test_render.py` | Prompt text from ETL rows |
| `test_orchestrator.py` | Full matches, triggers, idempotency, backlog equals live, restarts, retries, report |
| `test_llm_agents.py` | Agents against a mocked API: parsing, retries, per-role settings, prompt templates |
| `test_graphql_data.py` | ETL GraphQL client against a fake DAB, no future leakage |
| `test_graphql_live.py` | Read-only checks against a real DAB (skips when unreachable) |
| `test_store_contract.py` | Memory and Cosmos stores behave the same (Cosmos part skips without `COSMOS_ENDPOINT`) |
| `test_api.py` | History GraphQL queries and errors |
| `test_servicebus.py` | Router, settling, publisher |

Fixtures in `tests/fixtures/` are synthetic and labelled so.

## 5. Conventions

*In short: keep components in their folders and secrets out of Git.*

- New code goes in the folder whose name says what it is ([code layout](README.md#code-layout-at-a-glance)).
- Original prompts stay unchanged in `docs/design/example-prompts/`; runtime prompts get a new versioned file.
- Secrets live in `.env`, Terraform outputs or Container App secrets; commands read them without printing.
- `.local/` holds run output and is never committed.
