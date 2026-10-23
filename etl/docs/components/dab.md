# Data API builder

> **In short:** Microsoft's Data API builder serves the SQL tables, views and the `statsAtSeq` and trend procedures as a GraphQL API with filtering, ordering and paging, configured by one JSON file. No API code is written; the same config runs locally in Docker and in Azure on Container Apps, where `dab.tf` turns GraphQL introspection off.

| | |
| --- | --- |
| **Status** | Deployed (internal ingress), anonymous read · every entity tested locally and read by the backend and engine on Azure |
| **Code** | [`dab/dab-config.json`](../../dab/dab-config.json) |
| **Image** | `mcr.microsoft.com/azure-databases/data-api-builder:2.1.5` |
| **URL (Azure)** | Internal only: `terraform -chdir=etl/infra output graphql_url` (apps in the shared Container Apps environment) |
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
| `Match` relationships | `teams` → `MatchTeam` (`dbo.matchTeams`), `players` → `MatchPlayer` (`dbo.matchPlayers`) | `matches { items { teams { items … } players { items … } } }` |
| `MatchWatermark` | view `dbo.matchWatermarks` | `matchWatermarks` |
| `StatDefinition` | `dbo.statDefinitions` | `statDefinitions` |
| `CanonicalEvent` | `dbo.canonicalEvents` | `canonicalEvents` |
| `PossessionSample` | `dbo.possessionSamples` | `possessionSamples` |
| `SpadlAction` | `dbo.spadlActions` | `spadlActions` ([SPADL](spadl.md)) |
| `StatsAtSeq` | procedure `dbo.statsAtSeq` | `executeStatsAtSeq(matchId, seq)` (plain list) |
| `TrendDefinition` | `dbo.trendDefinitions` | `trendDefinitions` |
| `TrendsAtSeq`, `TrendSpellsAtSeq`, `TrendMinutesAtSeq` | procedures `dbo.trendsAtSeq`, `dbo.trendSpellsAtSeq`, `dbo.trendMinutesAtSeq` | `executeTrendsAtSeq(matchId, seq)` etc. (plain lists; [trends](trends.md)) |

Every query supports `filter`, `orderBy`, `first` and `after`. Examples: [contracts](../../contracts/README.md#output-1-graphql-data-api-builder-anonymous-read).

## 2. Hosting

*In short: config mounted from a secret, managed identity to SQL, scales to zero.*

- The config file is a Container App secret mounted as a volume, so no registry or custom image is needed.
- DAB connects to SQL with its system-assigned managed identity (`db_datareader` and `EXECUTE` on `statsAtSeq` and the trend procedures, granted by `devtools azure-setup`).
- 0–1 replicas at 0.25 vCPU: the first request after idle can take about 30 s, longer if SQL is resuming.
- Authentication provider `Unauthenticated`, anonymous read only; on Azure the app has internal ingress, so only the backend and the engine (same environment) reach it.
