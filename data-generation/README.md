# Data generation

[Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![An existing synthetic match is prepared and replayed into Event Hubs](architecture.svg)

**A rendered GRF demo and telemetry adapter are implemented** ([run guide](docs/grf-demo.md)). Azure replay publishing is planned. A [reusable 90-minute GRF-derived recording](recordings/README.md) is implemented for algorithm benchmarks. Prepares and replays an existing generated match into the shared match-event stream. The benchmark recording is separate from production publishing.

| Part | Role |
| --- | --- |
| Existing generated match | Synthetic source events and provenance. |
| Replay runner | Prepare and publish events; hosting undecided. A local demo tool is an option. |
| Azure Event Hubs | Output consumed by ETL and the user backend. |

Preserve source timestamps, event IDs and provenance, and clearly label synthetic data. Existing ignored outputs remain in `.local/grf-runs/` at the repository root.

The [GRF simulator](../legacy/data/GoogleResearchFootball/README.md) remains archived for reference. Active generation tools in this folder run an installed instrumented runtime; archived scripts remain inactive. The demo is delivered through the local ETL adapter, not production Event Hubs.

[Repository plan](../README.md)
