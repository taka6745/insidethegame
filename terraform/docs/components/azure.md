# `./dev azure`

> **In short:** [`azure/azure.py`](../../azure/azure.py) deploys, plans, inspects and removes the whole stack; Terraform and the Azure CLI run in a pinned toolbox image.

| | |
| --- | --- |
| **Code** | `azure.py` (standard library only), `Dockerfile` (toolbox), `media.json`, `encode_media.sh`, `test_azure.py` |
| **Runs** | `./dev azure up\|down\|status\|plan [--yes] [--release]` ([deployment](../deployment.md)) |

- **Toolbox:** Terraform 1.13.4 (as `./dev terraform check`), Azure CLI, go-sqlcmd (ETL `azure-setup`) and azcopy, with the developer's mounted `~/.azure`; no other credentials.
- **Media:** `media.json` names the full-quality fixture (`redcastle-portalbion`, about 3.3 GB); `encode_media.sh` re-encodes the others once (720p25 H.264 about 1.75 Mbit/s, same segment names, timestamps and keyframes; about 1.1 GB each) into `.local/grf-demo-<fixture>-90-low/`. `azcopy sync` uploads in parallel, skips unchanged files and sends the playlist last; `up` checks the segment count.
- **Secrets:** read from state into `TF_VAR_*` (e.g. the guard's stream-start URL for the app stack), never on a command line or printed.
- **Tests:** `test_azure.py` fakes the toolbox and checks that `plan` passes the app the same inputs as `up`.
