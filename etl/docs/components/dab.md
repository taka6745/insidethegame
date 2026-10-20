# Data API builder

> **In short:** Microsoft's Data API builder serves the SQL tables and view as a GraphQL API with filtering, ordering and paging, configured by one JSON file. No API code is written; the same config runs locally in Docker and in Azure on Container Apps.

| | |
| --- | --- |
| **Status** | Deployed (dev), anonymous read |
| **Code** | [`dab/dab-config.json`](../../dab/dab-config.json) |
| **Image** | `mcr.microsoft.com/azure-databases/data-api-builder:2.1.5` |
| **URL (dev)** | `https://itg-etl-dev-dab.mangosmoke-bbf503ab.australiaeast.azurecontainerapps.io/graphql` |
| **Local** | `http://localhost:5000/graphql` (`python -m devtools local-up`) |

## 1. Entities

*In short: one GraphQL type per table, plus the view.*

| Entity | Source | GraphQL query |
| --- | --- | --- |
| `Match` | `dbo.matches` | `matches` |
| `RawEvent` | `dbo.rawEvents` | `rawEvents` |
| `KeyEvent` | `dbo.keyEvents` | `keyEvents` |
| `MinuteStat` | `dbo.minuteStats` | `minuteStats` |
| `MatchStatsAsOf` | view `dbo.matchStatsAsOf` | `matchStatsAsOfs` |

Every query supports `filter`, `orderBy`, `first` and `after`. Examples: [contracts](../../contracts/README.md#output-1-graphql-data-api-builder-anonymous-read).

## 2. Hosting

*In short: config mounted from a secret, managed identity to SQL, scales to zero.*

- The config file is a Container App secret mounted as a volume, so no registry or custom image is needed.
- DAB connects to SQL with its system-assigned managed identity (`db_datareader` granted by `devtools azure-setup`).
- 0–1 replicas at 0.25 vCPU: the first request after idle can take about 30 s, longer if SQL is resuming.
- Authentication provider `Unauthenticated`, anonymous read only (synthetic dev data; LATER: restrict to the services).
