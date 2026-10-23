# Data generation

> **In short:** renders synthetic fictional-league matches with Google Research Football and replays them through the feed, a simulated external provider, as live matches. Implemented and tested ([status](docs/overview.md)).

[Documentation](docs/README.md) · [Development guide](docs/development.md) · [Shared local setup](../DEVELOPMENT.md)

![Recordings and media go into the feed, which publishes to Event Hubs and serves played HLS](architecture.svg)

The [feed](docs/components/feed.md) plays several matches at once, each with its own `matchId`. The feed also runs the demo: **Start demo** kicks off exactly three fixtures (main game Redcastle Town–Port Albion first), from kick-off or from a recorded seed ([feed §2a](docs/components/feed.md#2a-demo-and-seeds)).

| Part | Role |
| --- | --- |
| [`grf_demo/`](docs/components/grf-demo.md) | Offline: render a tactically scripted match, derive [Opta-style events](contracts/README.md), package HLS |
| [`recordings/`](docs/components/recordings.md) | Three shipped 90-minute matches and their exports |
| [`feed/`](docs/components/feed.md) | Live: MA1, `MatchEvent` v2, MA3 and POS to Event Hubs at video pace; played HLS over HTTP |

Every message and recording is labelled `synthetic: true` with its provenance; none is Stats Perform data or an actual match. GRF is Apache-2.0; see the [archived simulator and provenance](../legacy/data/GoogleResearchFootball/README.md). Raw telemetry and video stay in ignored `.local/`.

[Repository plan](../README.md)
