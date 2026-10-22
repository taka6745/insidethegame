# Data generation

[Documentation](docs/README.md) · [Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![Recordings and media go into the feed, which publishes to Event Hubs and serves played HLS](architecture.svg)

**Implemented and tested; runs in the local stack; Azure applied 22 Oct for the Azure test (acceptance pending).** Renders synthetic real-club matches with Google Research Football and replays them through the [feed](docs/components/feed.md), a simulated external provider, as live matches: several at once, each with its own `matchId`. The feed also runs the judge demo: **Start demo** kicks off exactly three fixtures (main game Arsenal–Liverpool first), from kick-off or from a recorded seed ([feed §2a](docs/components/feed.md#2a-demo-and-seeds)).

| Part | Role |
| --- | --- |
| [`grf_demo/`](docs/components/grf-demo.md) | Offline: render a tactically scripted match, derive [Opta-style events](docs/opta-events.md), package HLS |
| [`recordings/`](recordings/README.md) | Three shipped 90-minute matches and their exports |
| [`feed/`](docs/components/feed.md) | Live: MA1, `MatchEvent` v2, MA3 and POS to Event Hubs at video pace; played HLS over HTTP |

Every message and recording is labelled `synthetic: true` with its provenance; none is Stats Perform data or an actual match. GRF is Apache-2.0; see the [archived simulator and provenance](../legacy/data/GoogleResearchFootball/README.md). Raw telemetry and video stay in ignored `.local/`.

[Repository plan](../README.md)
