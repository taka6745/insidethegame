# Original design

> **In short:** the data-generation plan from the design stage (`data-generation/README.md` at commit `7fd5838`, and the "Synthetic Match Generator" box on `legacy/design/plan.excalidraw`), kept unchanged for history. What was built is in [../decisions.md](../decisions.md).

| | |
| --- | --- |
| **Board** | Synthetic Match Generator: GRF Engine → Azure Event Hubs |
| **Superseded** | [event-coverage.md](event-coverage.md) (research, 19 October 2026) by [../../contracts/README.md](../../contracts/README.md) |

---

**Planned demo tooling; not implemented or deployed.** Prepares and replays an existing generated match into the shared match-event stream. No specific source file has been selected.

| Part | Role |
| --- | --- |
| Existing generated match | Synthetic source events and provenance. |
| Replay runner | Prepare and publish events; hosting undecided. A local demo tool is an option. |
| Azure Event Hubs | Output consumed by ETL and the user backend. |

Preserve source timestamps, event IDs and provenance, and clearly label synthetic data. Existing ignored outputs remain in `.local/grf-runs/` at the repository root.

The GRF simulator remains archived for reference. This folder adds no simulator or replay code yet.
