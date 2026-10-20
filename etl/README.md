# Match data / ETL

[Development](docs/development.md) · [Demo API](docs/demo-api.md)

![ETL owns standard statistics and historical events](architecture.svg)

**Working local demo:** GRF recording → Event Hubs → ETL-owned replay prefix → stored history + standard statistics → GraphQL. Service Bus announces the newest readable snapshot of each Event Hubs batch; its history includes every earlier event, so a backlog costs one commit. The user backend reads these results; it does not recalculate standard cards.

| Data | Local demo | Planned Azure |
| --- | --- | --- |
| Original events + immutable history | `etl_history` PostgreSQL database | Azure SQL |
| Standard stat projections | `etl_stats` PostgreSQL database | Cosmos DB |
| Ingestion | Event Hubs emulator + recorded GRF match | Event Hubs + Stream Analytics |
| Read API | Python GraphQL on port 8000 | Container Apps GraphQL |

`demo_etl/` is a replaceable demo implementation, separate from the future Stream Analytics job. It preserves corrections, tombstones and snapshot watermarks. Possession comes from measured simulator ownership; unsupported metrics are unavailable. Opta-style v3 events (location, possession IDs, qualifiers, stoppage-time clock) are accepted and served through GraphQL — unit-tested and run with the 90-minute recording in the integrated Docker stack (20 October 2026). Synthetic football is not an official Opta feed or a real fixture.

The broker adapters use the Azure SDKs; prefix recovery remains specific to this recording stub. No Azure SQL/Cosmos writer or ASA job is implemented here. The local DAB container remains an independent SQL infrastructure check.
