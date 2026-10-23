# Development

> **In short:** a plain Python virtual environment, no Docker needed. Each Azure dependency has a local stand-in (in-memory store, fixture files, JSONL transport, fake agents), so the whole engine runs offline; the same code then points at Azure dev resources one piece at a time.

| | |
| --- | --- |
| **Needs** | Python 3.11; Azure CLI and Terraform only for Azure work; Docker only to build the image |
| **Settings** | Ignored `narrative-engine/.env` (never committed) |
| **Tests** | `pytest tests` (a few skip without Cosmos or a local DAB). The store contract also runs against the local Cosmos emulator: `COSMOS_ENDPOINT=http://127.0.0.1:18081 COSMOS_KEY=<emulator key>` |
| **Whole product locally** | `ACCEPT_EULA=Y ./dev up backend` runs this engine as `narrative-live` (GraphQL :18012, Cosmos emulator, local model from `.local/backend-llm.env`) on the ETL's `etl-stream` + `etl-dab` stand-in, with targets and prompts from the user backend: [../../DEVELOPMENT.md](../../DEVELOPMENT.md); logs with `./dev logs narrative-live`. Compose sets `DEMO_SEEDS=1`, so demo control can record and restore seeds ([demo](components/demo.md)) |

## 1. Setup

*In short: one virtual environment for the engine, its tests and the fixture tools.*

```sh
cd narrative-engine
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # requirements.txt plus pytest
.venv/bin/python -m pytest tests
```

Run everything from `narrative-engine/`: tests import `narrative_engine` and the developer commands run as `python -m devtools.<command>`.

## 2. Local stand-ins

*In short: every Azure service has an offline replacement, swapped in by settings.*

| Azure piece | Local stand-in | Switch |
| --- | --- | --- |
| Cosmos DB | `MemoryStore` (dictionaries) | `COSMOS_ENDPOINT` unset |
| ETL GraphQL | `FixtureMatchData` over `tests/fixtures/` (synthetic match `itg-syn-0001` and its SPADL actions, `devtools/spadl_fixture.py`), or the ETL's local DAB in Docker on :5000 | `--data fixture\|graphql`, `--actions` |
| Service Bus in | ETL notifications JSONL (`etl/.local/notifications.jsonl` from the ETL's `load-local`, or `tests/fixtures/itg-syn-0001-notifications.jsonl`) | `devtools.local` |
| Service Bus out | `.local/narratives.jsonl` | `devtools.local --out` |
| Foundry | `FakeAgents`, or any OpenAI-compatible API in `.env` | `--agents fake\|llm` |

The `MemoryStore` and Cosmos store share a contract test, and a fake-agent run over the fixture matches a run against the Azure dev DAB, so passing locally means the same behaviour in Azure.

## 3. Common runs

*In short: from fastest and most offline to closest to production.*

```sh
# 1. Whole match, fake agents, offline (seconds)
.venv/bin/python -m devtools.local tests/fixtures/itg-syn-0001-notifications.jsonl

# 2. Real models, two buckets (about 5 minutes on Foundry)
.venv/bin/python -m devtools.local tests/fixtures/itg-syn-0001-notifications.jsonl \
  --agents llm --buckets neutral:casual,home:analyst

# 3. Real models and the Azure dev ETL data
ETL_GRAPHQL_URL=<dev graphql url> .venv/bin/python -m devtools.local \
  tests/fixtures/itg-syn-0001-notifications.jsonl --data graphql --match-id itg-syn-0001-cloud4 --agents llm

# 4. The full service on your machine against Azure dev (Service Bus, Cosmos DB)
.venv/bin/python -m devtools.azure env      # settings into .env
USER_BACKEND_URL=<backend url> .venv/bin/python -m narrative_engine.service   # no backend: paused, /health 503
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
| `test_graphql_live.py` | Read-only checks against the shared stack's ETL GraphQL (`ETL_GRAPHQL_URL`, default `:15001`): a Riverton Rovers–Forgeham United feed run's MA3 rows, key events, SPADL actions and golden stats equal the recording's test data up to its watermark (skips without such a run) |
| `test_store_contract.py` | Memory and Cosmos stores behave the same (Cosmos part skips without `COSMOS_ENDPOINT`) |
| `test_api.py` | History GraphQL queries and errors |
| `test_servicebus.py` | Router: concurrent matches, model limit across matches, model gate order, purge (one, all, restart), final period from MA1, `eventSeq`, health without the backend; settling, publisher |
| `test_backend_sources.py` | Audience targets and prompts from the user backend (mocked HTTP): ETag, framing, placeholder validation, no fallback, pinning, health problems |
| `test_shipped_fixtures.py` | The authored commentary fixtures bind byte for byte to their archived recording (`fixtures/archive/`) |
| `test_follows.py`, `test_decisions.py`, `test_storylines*.py`, `test_recording_run.py`, `test_model_roles.py` | Story follows, decision models, storylines over the recording, backlog equals live, model per role |

Test doubles live in `tests/doubles/` (fake agents and decisions, `FixtureMatchData`, fixed targets and topics); helpers shared by several test modules (a mocked user backend, `EtlAsOf`, ETL trend rows) in `tests/support.py`; the Riverton Rovers–Forgeham United recording as test data in `tests/riverton_forgeham.py`.

Fixtures in `tests/fixtures/` are synthetic and labelled so.

## 5. Conventions

*In short: keep components in their folders and secrets out of Git.*

- New code goes in the folder whose name says what it is ([code layout](README.md#code-layout-at-a-glance)).
- Original prompts stay unchanged in `docs/design/example-prompts/`; runtime prompts get a new versioned file.
- Secrets live in `.env`, Terraform outputs or Container App secrets; commands read them without printing.
- `.local/` holds run output and is never committed.
