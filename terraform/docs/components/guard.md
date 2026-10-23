# Spend guard

> **In short:** budgets only email; Stream Analytics runs only while matches play; one last resort near the end of the credit keeps the viewer serving. Applied first by `up`, kept by `down`.

| | |
| --- | --- |
| **Code** | [`guard/`](../../guard/): `main.tf`, `guard.ps1`, `tests/` |
| **Resource group** | `rg-itg-guard` (tag `insidethegame-guard`), state `.local/terraform/guard` |

| Piece | What it does |
| --- | --- |
| `budget-insidethegame` | A$15/day as a A$450 monthly budget (no daily grain in Azure). Emails at actual 50/80/100 % and forecast 100 %. Never stops anything |
| `budget-insidethegame-credit` | The trial credit (A$285 from 1 Oct; about A$281 left on 22 Oct; expires 17 Nov). Emails at actual 50/75 % and forecast 100 %; at actual 90 % the last resort runs |
| Last resort | Stops Stream Analytics, the feed, the SPADL post-processor and the feed's PostgreSQL. Frontend, backend, DAB, engine and their stores keep running, so the viewer and replays still work. Forecasts don't trigger it: a forecast runs to the period end and would stop the demo too early |
| Stream Analytics schedule | `etl/infra/stream_schedule.tf`: an Event Hubs alert (match events in the last minute) starts the job, resuming after its last output; 30 minutes without events stops it. Demo control also calls the stream-start webhook on Start (`DEMO_STREAM_START_URL`), so only the job's own start (75–90 s) remains |
| Runbook | `guard.ps1` in an Automation account (East US: Free Trial can't create one in Australia East), modes `stream-start`, `stream-stop`, `last-resort`, one webhook each. Its custom role reads, starts and stops only |

`./dev azure up` restores anything the runbook stopped. Azure's own spending limit (on for Free Trial) is the hard stop at zero credit.
