# Develop match data

![Service boundary](../architecture.svg)

**Own:** standard stat calculations/state, historical events, key moments and the GraphQL API for all of them.

```text
                         → Cosmos DB: computed stats →
Events → ETL processing                               ETL GraphQL → consumers
                         → Azure SQL: event history  →
```

**Start:** `./dev test azure` checks the independent messaging/SQL/DAB infrastructure. `http://localhost:15000/graphql` currently exposes only a tiny SQL fixture. No Stream Analytics job or Cosmos stat writer runs locally. For backend work, `./dev up backend` starts fake ETL/narrative services instead.

**Build next:** event storage/migrations, Stream Analytics processing and Cosmos stat state; then the GraphQL routes for computed values and separately filtered/paginated history. Choose the GraphQL composition/adapter implementation for both stores; the existing SQL-only DAB setup is not the complete API. Publish minute/key-event notifications for the narrative engine.

**Prove it:** known events produce correct stored stats/history; test duplicates, late events, halftime and VAR corrections. Readable state must precede its update notification. Backend cards and agent answers reuse these computed values; they must not recreate standard counters from events.

**Still to agree:** how standard-stat refreshes are signalled and versioned. Event Hubs remains the custom-calculation event source; fetching standard values is a separate GraphQL operation. See [contracts](../../local/contracts.md).

**Azure:** Event Hubs, Stream Analytics, Cosmos DB, Azure SQL, Service Bus and a GraphQL API on Container Apps. ETL owns its ASA job, event-time policy and cloud validation. Terraform still needs the ETL-specific Cosmos resources.
