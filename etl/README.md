# Match data / ETL

![Match events become queryable history, stats and notifications](architecture.svg)

**Planned service; not implemented or deployed.** Turns timestamped match events into history, a key-event ledger and computed match statistics.

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
