# Develop match data

![Service boundary](../architecture.svg)

**Own:** event history, key events, minute deltas, computed stats and their GraphQL API.

```text
Event Hubs → Stream Analytics → Azure SQL → GraphQL
                           ↘ Service Bus
```

**Start:** [Docker setup](../../DEVELOPMENT.md), then `./dev test azure`. Open `http://localhost:15000/graphql`. Real Data API builder queries a tiny SQL fixture table; **no Stream Analytics job runs locally**.

**Build next:** put SQL migrations, Stream Analytics query/config and their tests here. Start with raw-event passthrough, then key-event filtering and minute deltas. Add the computed-stat view and DAB entities. Publish `KeyEventDetected` / `MinuteClosed` to `match-notifications`.

**Prove it:** replay known events; compare stored history and aggregated values; test duplicates, late data, halftime and VAR negative deltas. A closed minute must have queryable data before its notification is consumed. Agree timing/correction rules in [contracts](../../local/contracts.md).

**Azure:** Event Hubs, Stream Analytics, Azure SQL, Service Bus; DAB runs on Container Apps. Shared infrastructure is in [terraform/](../../terraform/README.md). This service owns the ASA job, event-time policy and Azure integration. Local fixture insertion is not an ETL substitute.
