# Data generation

![An existing synthetic match is prepared and replayed into Event Hubs](architecture.svg)

**Planned demo tooling; not implemented or deployed.** Prepares and replays an existing generated match into the shared match-event stream. No specific source file has been selected.

| Part | Role |
| --- | --- |
| Existing generated match | Synthetic source events and provenance. |
| Replay runner | Prepare and publish events; hosting undecided. A local demo tool is an option. |
| Azure Event Hubs | Output consumed by ETL and the user backend. |

Preserve source timestamps, event IDs and provenance, and clearly label synthetic data. Existing ignored outputs remain in `.local/grf-runs/` at the repository root.

The [GRF simulator](../legacy/data/GoogleResearchFootball/README.md) remains archived for reference. This folder adds no simulator or replay code yet.

[Repository plan](../README.md)
