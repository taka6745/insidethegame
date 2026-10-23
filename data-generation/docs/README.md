# Data generation documentation

> **In short:** data generation renders synthetic football matches with Google Research Football and replays them through the feed, a simulated external provider, as live matches on Event Hubs and HLS. Start with the overview; each component page maps to one folder.

| | |
| --- | --- |
| **Status** | [overview](overview.md) |
| **Event contract** | [../contracts/README.md](../contracts/README.md) (Opta-style v3) |
| **Run locally** | [development.md](development.md) |

Every page opens with an **In short** summary and a facts table; numbered sections open with a one-line *In short*.

## Contents

```
docs/
├── README.md               this index
├── overview.md             what it does, status, inputs and outputs, glossary
├── architecture.md         diagram, components, a run end to end, data model
├── components/             one page per code folder
│   ├── feed.md             feed/: the simulated provider service, Start demo and seeded runs
│   ├── grf-demo.md         grf_demo/: render, translate and package a match
│   └── recordings.md       recordings/: the three shipped matches and their provenance
├── development.md          setup, commands, tests
├── deployment.md           local stack and Azure Terraform
├── decisions.md            design versus implementation, open items
└── design/                 original design material (not updated)
    ├── original-design.md  the design-stage plan
    └── event-coverage.md   event research, superseded by ../contracts/README.md
```

## Code layout at a glance

| Folder | Contents | Page |
| --- | --- | --- |
| `feed/` | Simulated provider service (`Dockerfile`, migrations, tests) | [feed](components/feed.md) |
| `grf_demo/` | Capture, telemetry, Opta-style exports, roster, source patches | [grf-demo](components/grf-demo.md) |
| `recordings/` | Shipped recordings and their exports | [recordings](components/recordings.md) |
| `contracts/` | The Opta-style event contract of every recording | [contracts](../contracts/README.md) |
| `tests/` | Generator, recording and export tests | [development](development.md#2-tests) |
| `generate-grf.sh`, `prepare-grf-source.sh` | Render one fixture | [grf-demo](components/grf-demo.md#1-run) |
