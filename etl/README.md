# Match data / ETL

[Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![ETL owns standard statistics and historical events](architecture.svg)

**Planned service.** ETL owns standard stat calculations, corrections and match history. Consumers use its GraphQL API.

| Component | Owns |
| --- | --- |
| Event Hubs | Incoming match events |
| Stream Analytics | Event processing and standard stat aggregation |
| Azure Cosmos DB | Precomputed standard stat state |
| Azure SQL | Raw events and historical/key-event queries |
| ETL GraphQL on Container Apps | Read-only access to stats and event history |
| Service Bus | Minute/key-event triggers for narrative generation |

The user backend **fetches standard stats**, then selects and delivers the viewer's cards. Agents use ETL GraphQL for specific historical investigations. Backend custom calculations are reserved for requests the existing statistics cannot answer; one shared Event Hubs consumer supports those custom live values.

The local DAB container currently serves a tiny SQL fixture. Routing GraphQL across Cosmos stats and SQL history remains to implement; the backend harness uses explicitly fake upstream services. Neither is a completed ETL pipeline.

Timing, late events, duplicate handling and VAR corrections belong here. Agree those contracts before production integration.

[Original design board](../legacy/design/plan.excalidraw) · [Repository plan](../README.md)
