# Spend guard

> **In short:** budgets only email; Stream Analytics runs only while matches play; one last resort near the end of the credit keeps the viewer serving; the hard stop at the credit itself stops everything. Applied first by `up`, kept by `down`.

| | |
| --- | --- |
| **Code** | [`guard/`](../../guard/): `main.tf`, `guard.ps1`, `tests/` |
| **Resource group** | `rg-itg-guard` (tag `insidethegame-guard`), state `.local/terraform/guard` |

| Piece | What it does |
| --- | --- |
| `budget-insidethegame` | A$15/day as a A$450 monthly budget (no daily grain in Azure). Emails at actual 50/80/100 % and forecast 100 %. Never stops anything |
| `budget-insidethegame-credit` | The trial credit (A$285 from 1 Oct; expires 17 Nov). Emails at actual 50/75 % and forecast 100 %; at actual 90 % the last resort runs; at actual 100 % the hard stop runs |
| Last resort | Stops Stream Analytics, the feed, the SPADL post-processor and the feed's PostgreSQL. Frontend, backend, DAB, engine and their stores keep running, so the viewer and replays still work. Forecasts don't trigger it: a forecast runs to the period end and would stop the demo too early |
| Hard stop | Stops every container app and PostgreSQL server in the four stack groups (and Stream Analytics). Nothing serves until `./dev azure up`. Budgets evaluate a few times a day, so up to a day's spend can still land after it. The forecast never triggers it: a forecast is Azure's extrapolation of recent days to the period end, so two heavy development days read as a month of them |
| Stream Analytics schedule | `etl/infra/stream_schedule.tf`: an Event Hubs alert (match events in the last minute) starts the job, resuming after its last output; 30 minutes without events stops it. Demo control also calls the stream-start webhook on Start (`DEMO_STREAM_START_URL`), so only the job's own start (75–90 s) remains |
| Runbook | `guard.ps1` in an Automation account (East US: Free Trial can't create one in Australia East), modes `stream-start`, `stream-stop`, `last-resort`, `hard-stop`, one webhook each. Its custom role reads, starts and stops only |

`./dev azure up` restores anything the runbook stopped; `./dev azure guard` applies this stack alone. Azure's own spending limit (on for Free Trial) is the hard stop at zero credit.
