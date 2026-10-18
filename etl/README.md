# Match data / ETL

![Match events become queryable history, stats and notifications](architecture.svg)

**Implemented; deployed to a personal dev environment and tested end to end.** Consumers: read the [contracts](contracts/README.md) (GraphQL queries, Service Bus messages, key-event conventions). Turns timestamped match events into history, a key-event ledger and computed match statistics.

| Part | Status |
| --- | --- |
| [Event contract](contracts/) — Opta MA1/MA3 style | Implemented |
| [Seeder](seeder/) — synthetic match + replay to Event Hubs | Implemented, tested |
| [SQL](sql/migrations/) tables + `matchStatsAsOf` view, [DAB config](dab/dab-config.json) | Tested locally and in Azure against the [reference pipeline](etltools/pipeline.py) |
| [Stream Analytics query](stream-analytics/), [Terraform](infra/) | Deployed (dev, Australia East); a 10× replay matches the reference for GraphQL and Service Bus |

```sh
cd etl && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows path shown
.venv/Scripts/python -m pytest tests
.venv/Scripts/python -m etltools.dev local-up                  # SQL Server + DAB in Docker, GraphQL on :5000
.venv/Scripts/python -m seeder.replay seeder/matches/itg-syn-0001.jsonl --speed 10 --target file --match-id demo
.venv/Scripts/python -m etltools.dev load-local .local/replays/demo.jsonl --window 6
.venv/Scripts/python -m etltools.dev verify .local/replays/demo.jsonl --window 6
```

Azure (your own dev copy): fill `infra/local.auto.tfvars` from the example, then

```sh
cd infra && terraform init && terraform apply && cd ..
.venv/Scripts/python -m etltools.dev azure-setup            # schema + database users for the managed identities
.venv/Scripts/python -m etltools.dev asa start              # bills while running; `asa stop` when done
ETL_EVENTHUB_CONNECTION_STRING=$(terraform -chdir=infra output -raw eventhub_send_connection_string)   .venv/Scripts/python -m seeder.replay seeder/matches/itg-syn-0001.jsonl --speed 10 --target eventhub --match-id demo1
.venv/Scripts/python -m etltools.dev verify .local/replays/demo1.jsonl --graphql "$(terraform -chdir=infra output -raw graphql_url)"
.venv/Scripts/python -m etltools.dev check-notifications .local/replays/demo1.jsonl
```

At ⅓ streaming unit the job runs about two minutes behind a 10× replay.

| Azure component | Role in this design |
| --- | --- |
| Event Hubs | Incoming match-event stream. |
| Stream Analytics | Pass through raw events; filter key events; aggregate one-minute team statistics. |
| Azure SQL Database, serverless | Store `rawEvents`, `keyEvents`, `minuteStats`; expose `matchStatsAsOf`. |
| Data API builder on Container Apps | Serve the stored data through GraphQL. |
| Service Bus | Publish `KeyEventDetected` and `MinuteClosed` notifications. |

**Input:** match events with match ID, event ID, wall-clock timestamp and match time.

For the demo, [data generation](../data-generation/README.md) prepares and replays an existing generated match into Event Hubs. ETL consumes that stream. The replay source and runner are still to be selected.

**Outputs:** GraphQL history and computed statistics for the narrative engine and user backend; Service Bus notifications for narrative orchestration. The user backend consumes live match events directly from Event Hubs through one shared consumer.

The draft aligns kickoff with a wall-clock minute, uses event-time windows and allows for late arrivals. VAR corrections contribute negative goal deltas. These timing and correction contracts still need implementation and testing.

[Original design board](../legacy/design/plan.excalidraw) · [Repository plan](../README.md)

**To update later:** this account is Contributor, so it cannot create role assignments. Event Hubs and Service Bus therefore use scoped shared access keys (Stream Analytics listen/send, seeder send, consumers listen). When someone with Owner or RBAC Administrator rights is available, switch them to managed identity / Entra roles: search `LATER` in [infra/](infra/) and [seeder/replay.py](seeder/replay.py).
