# Deployment

> **In short:** only demo control is deployed from this folder: an internal Container App built from the backend image plus the script. Everything else here is local only.

| | |
| --- | --- |
| **Terraform** | [`terraform/demo_control.tf`](../../terraform/demo_control.tf) |
| **Image** | `demo-control.Dockerfile`: the user backend's runtime image + `demo_control.py` |
| **Scale** | Min 1, max 1 replica (one operator; start and cancel serialise in the process), 1 vCPU / 2 GiB |

- Internal ingress; nginx in the frontend exposes `/demo-api/` (`DEMO_CONTROL_UPSTREAM`). Without it `/demo-api/` returns 502 and the viewer hides the controls.
- Environment: `DEMO_FEED_URL`, `ETL_ADMIN_URL`, `ENGINE_ADMIN_URL`, `BACKEND_URL`, `DEMO_KEEP_WARM_URLS` (ETL data API, itself), `DEMO_SEED_ROOT` (`/seeds`, the Azure Files share); secrets `ETL_ADMIN_TOKEN`, `ENGINE_ADMIN_TOKEN`, `DEMO_STREAM_START_URL`.
- Demo build only: the `seeds` Azure Files share mounted at `/seeds`. Record seeds with `az containerapp exec … python /checks/demo_control.py record|capture` ([demo control](components/demo-control.md#2-seeds)).

The full Azure procedure is [terraform/docs/deployment.md](../../terraform/docs/deployment.md).
