# Devtools

> **In short:** developer commands that are not part of the deployed service: run a whole match locally, wire your machine to Azure dev, build and push the image, check what reached Service Bus, render an HTML report of a match, and rebuild test fixtures.

| | |
| --- | --- |
| **Status** | Implemented · used throughout development |
| **Code** | [`devtools/`](../../devtools/) at the service root: `local.py`, `azure.py`, `report.py`; fixture tools `spadl_fixture.py`, `bind_commentary.py`, `commentary_schema.py` ([fixtures](fixtures.md)). Not in the image (`.dockerignore` keeps only `narrative_engine/`) |
| **Run** | From `narrative-engine/`: `python -m devtools.<command>`. Test doubles (fake agents and decisions, the fixture reader, fixed targets and topics) come from `tests/doubles/` |
| **Secrets** | Read from Terraform outputs into the ignored `.env`; never printed |

## 1. Local runs (`local.py`)

*In short: replay ETL notifications through the real orchestrator on your machine.*

```sh
python -m devtools.local NOTIFICATIONS.jsonl [options]
```

| Option | Effect |
| --- | --- |
| `--agents fake\|llm` | Fake agents (default) or real models from `.env` |
| `--data fixture\|graphql` | Replay file (default) or the ETL's GraphQL (`--graphql-url`) |
| `--match`, `--match-id` | Replay file and match ID override |
| `--pace N` | 0 = sequential and fast; N = N times the recorded timing, concurrent |
| `--buckets home:casual,away:analyst` | Buckets to write for (default all 12) |
| `--serve PORT` | Serve the history API during and after the run |
| `--out` | Narratives JSONL (default `.local/narratives.jsonl`) |

## 2. Azure dev helpers (`azure.py`)

*In short: everything needed to run against or deploy to Azure dev.*

| Command | What it does |
| --- | --- |
| `env` | Write Azure settings (ETL GraphQL URL, Service Bus strings, Cosmos endpoint) into `.env` |
| `build --tag X [--local]` | Build the image from a minimal context; `--local` uses Docker and pushes (ACR Tasks are blocked on the trial) |
| `check-narratives --match-id X` | Drain the `narrative-check` subscription: count a match's narratives by step and bucket, check each `MessageId` equals the narrative `id`, list one bucket's text |
| `report --match-id X [--no-open]` | Write `.local/report-<id>.html` from Cosmos and open it |
## 3. Report (`report.py`)

*In short: one HTML page showing how the engine thought about a match.*

A timeline in creation order: minute summaries (blue), compressions with the blocks they replaced (purple) and narrative steps with each bucket's text (green), with models, prompt versions and tokens. Filters hide kinds of card or pick one bucket. The page is self-contained and works in dark mode.

## 4. Fixture tools

*In short: regenerate the engine's test fixtures.*

| Command | Writes |
| --- | --- |
| `python devtools/spadl_fixture.py tests/fixtures/itg-syn-0001.jsonl tests/fixtures/itg-syn-0001-spadl.json` | SPADL actions for the synthetic match, with the ETL's converter (`etl/reference/spadl.py`) |
| `python devtools/bind_commentary.py CANONICAL_EXPORT --reviewed-hash <sha256>` | `fixtures/grf-narratives.json` from the authored text ([fixtures](fixtures.md)) |
