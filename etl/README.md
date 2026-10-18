# Match data / ETL

[Development](docs/development.md) · [Demo API](docs/demo-api.md)

![ETL owns standard statistics and historical events](architecture.svg)

**Working local demo:** GRF recording → ETL-owned replay prefix → stored history + standard statistics → GraphQL. The user backend reads these results; it does not recalculate standard cards.

| Data | Local demo | Planned Azure |
| --- | --- | --- |
| Original events + immutable history | `etl_history` PostgreSQL database | Azure SQL |
| Standard stat projections | `etl_stats` PostgreSQL database | Cosmos DB |
| Ingestion | Recorded GRF match, cursor bridge | Event Hubs + Stream Analytics |
| Read API | Python GraphQL on port 8000 | Container Apps GraphQL |

`demo_etl/` is a replaceable demo implementation, separate from the future Stream Analytics job. It preserves corrections, tombstones and snapshot watermarks. Possession comes from measured simulator ownership; unsupported metrics are unavailable. Synthetic football is not an official Opta feed or a real fixture.

No Azure SQL/Cosmos writer, production broker consumer or ASA job is implemented here. The local DAB container remains an independent SQL infrastructure check.
