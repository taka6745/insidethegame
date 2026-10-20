# Data generation

[Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![An existing synthetic match is prepared and replayed into Event Hubs](architecture.svg)

**A rendered GRF demo and telemetry adapter are implemented** ([run guide](docs/grf-demo.md), [event coverage](docs/event-coverage.md)). The removable backend lab replay publisher now sends the aligned recording through the Event Hubs emulator; a standalone production publisher remains planned. A [reusable 90-minute GRF-derived recording](recordings/README.md) is implemented for algorithm benchmarks. Prepares and replays an existing generated match into the shared match-event stream. The benchmark recording is separate from production publishing.

| Part | Role |
| --- | --- |
| Existing generated match | Synthetic source events and provenance. |
| Replay runner | Prepare and publish events; hosting undecided. A local demo tool is an option. |
| Azure Event Hubs | Output consumed by ETL and the user backend. |

Preserve source timestamps, event IDs and provenance, and clearly label synthetic data. Existing ignored outputs remain in `.local/grf-runs/` at the repository root.

The [GRF simulator](../legacy/data/GoogleResearchFootball/README.md) remains archived for reference. Active generation tools in this folder run an installed instrumented runtime; archived scripts remain inactive. The demo uses Event Hubs and Service Bus emulator delivery with ETL-owned history/stats; it is not deployed on Azure.

[Repository plan](../README.md)
