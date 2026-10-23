# Configuration

> **In short:** Compose and its env file define the stack; emulator topology and Postgres init are checked-in files; every credential here is a public local dummy value.

| | |
| --- | --- |
| **Code** | `compose.yaml`, `env.defaults`, `config/`, `sql/`, `settings.py`, `connections.env.example`, `verify.env.example`, `Dockerfile` (tools), `demo-control.Dockerfile`, `no-media/` |
| **Secrets** | None; model settings come from ignored `.local/*.env` |

| File | Holds |
| --- | --- |
| `compose.yaml` | Every service, its profile, health check and loopback port; read with `--env-file local/env.defaults` so no root `.env` leaks in |
| `env.defaults` | EULA `N`, agent and question limits (`QUESTION_TIMEOUT_SECONDS` 240 because custom-stat questions chain several model calls); ports and model concurrency default in `compose.yaml` |
| `config/eventhubs.json`, `config/servicebus.json` | Emulator hubs, consumer groups, topics and subscriptions (Terraform keeps the same names) |
| `sql/postgres.sql` | Creates `accounts` and `matchapp` on a fresh volume; schemas come from backend migrations |
| `settings.py` | Docker-network endpoints and the emulators' public keys for the checks |
| `connections.env.example` | Host-side values for running a service directly on the laptop (copy into that service's ignored `.env`) |
| `verify.env.example` | A second project's ports and name, beside `itg-local` |
| `no-media/` | Empty default media root when `.local/media` does not exist |

`./dev` recreates an emulator or DAB when its mounted config changes (they read it only at start), and DAB also when an ETL migration changes. Personal changes go in the ignored `local/compose.override.yaml`, which `./dev` loads; use Compose's `!override` tag to replace a port list. Image digests are pinned; upgrade them deliberately and rerun `./dev test azure`.
