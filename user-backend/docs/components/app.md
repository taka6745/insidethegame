# App

> **In short:** `backend/app.py` wires adapters, repositories and services into one FastAPI app; `store.py` owns the two Postgres pools and runs migrations; `domain.py` holds the one error type routes translate into JSON.

| | |
| --- | --- |
| **Code** | [`app.py`](../../backend/app.py), [`store.py`](../../backend/store.py), [`domain.py`](../../backend/domain.py) |
| **Entry point** | `uvicorn backend.app:from_env --factory` |
| **Tests** | Every API test builds the app through `tests/harness.py` |

## 1. Composition

*In short: swap adapters in `create_app`, never in services.*

`create_app(store, dab, …)` builds the `MatchRegistry`, `ConfigService`, ETL match-data port, narrative history, audience, prompt, question and product services, then mounts routers. `from_env()` reads the environment ([development](../development.md#2-configuration)) and adds the broker consumers. The lifespan initialises the store, config, prompts, questions, audiences and registry (restart rebuild), starts the stream tasks and `watch_models` (re-reads the `models` config row every 2 s and applies the backend roles), and closes projections and the DAB client on shutdown.

Optional routers: `/dev/*` with `ENABLE_DEV_FEED=1`; `/lab/*` with `ENABLE_FILTER_LAB=1`; the demo seed routes ([demo](demo.md)) with `DEMO_SEEDS=1` (local compose and the demo build; a production release leaves it off). `decide` (the follow offer's yes/no) comes from `DECISION_*` (Microsoft-Decision-1), else the question model. `/health` and `/ready` report `model` (`configured`/`missing`), `database`, the match count and open stream `gaps`; they return `503` until a model is configured and the database answers.

## 2. Store

*In short: pooled connections; each migration file runs once.*

`Store(accounts_dsn, match_dsn, schema='user_backend')` keeps one `psycopg_pool` per database (`POSTGRES_POOL_SIZE`, default 10). `connect()` is one Match App transaction with `search_path` set to the schema; `connect_accounts()` the Accounts one. `initialize()` takes an advisory lock and applies `migrations/*.sql` and `migrations/accounts/*.sql` in name order, recording each in `schema_migrations`.

## 3. Errors and the coding contract

*In short: `RuleError(code, message, status)` is the only application error.*

`RuleError` is returned as `{"code", "detail"}` with its HTTP status. The optional model-based coding-agent contract (`benchmarks/coding.py`) is outside the runtime package, for tests and experiments; generated code is never executed.
