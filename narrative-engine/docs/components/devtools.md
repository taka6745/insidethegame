# Devtools

> **In short:** developer commands that are not part of the deployed service: run a whole match locally, wire your machine to Azure dev, build and push the image, check what reached Service Bus, and render an HTML report of a match's summaries, compressions and narratives.

| | |
| --- | --- |
| **Status** | Implemented · used throughout development |
| **Code** | [`narrative_engine/devtools/`](../../narrative_engine/devtools/): `local.py`, `azure.py`, `report.py` |
| **Secrets** | Read from Terraform outputs into the ignored `.env`; never printed |

## 1. Local runs (`local.py`)

*In short: replay ETL notifications through the real orchestrator on your machine.*

```sh
python -m narrative_engine.devtools.local NOTIFICATIONS.jsonl [options]
```

| Option | Effect |
| --- | --- |
| `--agents fake\|llm` | Fake agents (default) or real models from `.env` |
| `--data fixture\|graphql` | Replay file (default) or the ETL's GraphQL (`--graphql-url`) |
| `--match`, `--match-id` | Replay file and match ID override |
| `--pace N` | 0 = sequential and fast; N = N times the recorded timing, concurrent |
| `--presence '{"home:casual": 1}'` | Simulated viewers (default all 12) |
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
| `send-presence --match-id X --counts '{…}' --minutes N` | Act as the user backend and send presence with heartbeats |

## 3. Report (`report.py`)

*In short: one HTML page showing how the engine thought about a match.*

A timeline in creation order: minute summaries (blue), compressions with the blocks they replaced (purple) and narrative steps with each bucket's text (green), with models, prompt versions and tokens. Filters hide kinds of card or pick one bucket. The page is self-contained and works in dark mode.
