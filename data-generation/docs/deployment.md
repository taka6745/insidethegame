# Deployment

> **In short:** the feed simulates a third-party provider, so on Azure it gets its own resource group, PostgreSQL and Blob Storage, and only a send-only key for our Event Hubs. Terraform in [`infra/`](../infra/); deployed by `./dev azure up` ([deployment](../../terraform/docs/deployment.md)).

| | |
| --- | --- |
| **Status** | Azure: [PLAN §11](../../PLAN.md#11-azure-judge-build); local Docker (`local/compose.yaml`, service `feed`); Terraform mock-tested |
| **Demo seeds** | `demo_seeds` variable sets `DEMO_SEEDS` (Terraform default off; `./dev azure up` turns it on, `--release` leaves it off) |
| **Image** | `data-generation/feed/Dockerfile`, target `runtime`; recordings and media are never baked in |
| **Azure** | `rg-itg-feed-dev`: Container App (internal ingress, 1 replica), PostgreSQL Flexible B1ms, Storage account |
| **Shares** | Only the ETL's Container Apps environment (trial: one per region) and registry; `seeder-send` key on `match-events` |

## 1. Local stack

*In short: one container, its own database, two volumes.*

| Mount | Mode | Holds |
| --- | --- | --- |
| `data-generation/recordings` → `/recordings` | read-only | Recordings |
| `ITG_MEDIA_ROOT` (`./dev`: `.local/media/`, hard links to each `.local/grf-demo-<fixture>-90/hls`) → `/media-source` | read-only, optional | Packaged HLS, `{fixture}/hls/` |
| `feed-media` → `/live-media` | feed only | Played segments |

## 2. Azure

*In short: Blob Storage replaces the volumes; the play-gate is unchanged.*

| Container (private) | Holds |
| --- | --- |
| `recordings` | `*.json`, downloaded at start |
| `media` | `{fixture}/hls/match.m3u8` and segments, uploaded by `./dev azure up` |
| `live` | `{matchId}/live.m3u8` and segments, copied server-side from `media` only once played |

Media upload: [`terraform/azure/media.json`](../../terraform/azure/media.json) keeps the main game (Redcastle Town–Port Albion) at full quality; the other fixtures are re-encoded to about 1.75 Mbit/s (same segments and timestamps) before `azcopy` uploads them.

`FEED_BLOB_CONNECTION_STRING` switches the feed to Blob Storage ([`adapters/blob.py`](../feed/adapters/blob.py)). `GET /hls/{matchId}/…` streams from `live`, so the frontend (`/media/hls/`) and backend (`FEED_HLS_BASE`) see the same HTTP origin as locally. The admin API stays inside the environment; the frontend's `/feed-api/` reaches it behind basic auth.
