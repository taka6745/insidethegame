# dev/

> **In short:** the developer console at `/dev/`: feed runs and purge, demo settings, audience templates, narrative prompts, backend config tables, demo profiles and pipeline health. Every editor is revision-checked; a conflict keeps the draft.

| | |
| --- | --- |
| **Routes** | `/dev-api/` → backend `/dev/` (`ENABLE_DEV_FEED=1`); `/feed-api/` and `/purge-api/{owner}` (nginx `ENABLE_DEV_ADMIN=1`) |
| **Auth** | Basic auth when `DEV_ADMIN_PASSWORD` is set ([deployment](../deployment.md)) |
| **Never called by** | The viewer or the lab (`tests/dev.test.ts`) |

| Files | Responsibility |
| --- | --- |
| `api.ts` | `DevApi`: every developer route; purge in order feed → ETL → engine → backend, stopping at the first failure (rerun is safe) |
| `matches.ts` | Recordings and runs: start a fixture at the next minute, purge one match or all; demo settings (fixtures, main game, stagger, run cap, start points) |
| `audiences.ts` | Audience template per fixture: layers, options, viewer labels, enabled buckets |
| `prompts.ts` | Narrative prompt versions: save, activate; placeholders from the active version |
| `config.ts` | JSON editors for backend config tables (`CONFIG_TABLES` in `api.ts`) |
| `profiles.ts` | Demo profiles and their default audiences |
| `main.ts` | Wiring, notices, pipeline health with stream gaps |
