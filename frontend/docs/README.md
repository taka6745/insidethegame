# Frontend documentation

> **In short:** the viewer (match picker, live match, questions, follows, clips), the filter lab and the `/dev/` console: static TypeScript modules behind one nginx. Start with the overview, then the architecture; each component page maps to one folder.

| | |
| --- | --- |
| **Status** | Implemented, tested and deployed ([overview](overview.md)) |
| **Pages** | `/` viewer, `/lab/` filter lab, `/dev/` console |
| **Runtime dependency** | Backend (`/viewer-api/`), demo control (`/demo-api/`), feed HLS (`/media/hls/`) |

Every page follows the same layout: an **In short** summary and a facts table at the top, then numbered sections that each open with a one-line *In short*.

## Contents

```
docs/
├── README.md                 this index
├── overview.md               what the viewer does, status, behaviour
├── architecture.md           diagram, routes, snapshots, limits, live HLS and replay
├── components/               one page per folder in frontend/
│   ├── match.md              the viewer (/)
│   ├── lab.md                the filter lab (/lab/)
│   ├── dev.md                the developer console (/dev/)
│   ├── shared.md             DOM and HTTP helpers shared by all three
│   ├── tools.md              build scripts used by the image
│   ├── devtools.md           contract mock, headless check, bundle and proxy checks, icon harness
│   ├── benchmarks.md         static transfer and state-update check
│   └── assets.md             icons, league artwork, provenance
├── development.md            run locally, commands, tests
├── deployment.md             Azure Container App, nginx settings, public demo API, edge proxy
├── decisions.md              choices, production boundary, open items
└── design/                   original design material (not updated)
    └── references.md         real-world references behind the design
```

## Where to start

| If you want to… | Read |
| --- | --- |
| Know what a viewer sees | [overview.md](overview.md) |
| See which API the browser calls and what it receives | [architecture.md](architecture.md), [local/contracts](../../local/contracts/README.md) §7a, §8 |
| Run it on your machine | [development.md](development.md) |
| Deploy it | [deployment.md](deployment.md) |
| Know why it is built this way | [decisions.md](decisions.md) |

## Code layout at a glance

| Folder | Contents | Page |
| --- | --- | --- |
| `match/` | The viewer | [match](components/match.md) |
| `lab/` | Filter lab | [lab](components/lab.md) |
| `dev/` | Developer console | [dev](components/dev.md) |
| `shared/` | `dom.ts`, `http.ts` | [shared](components/shared.md) |
| `tools/` | `build.sh`, `vendor.sh`, `nginx-setup.envsh` (in the image) | [tools](components/tools.md) |
| `devtools/` | Developer checks (not shipped) | [devtools](components/devtools.md) |
| `benchmarks/` | `client.ts` | [benchmarks](components/benchmarks.md) |
| `assets/` | Icons, league artwork, reference sheets | [assets](components/assets.md) |
| `tests/` | `node --test` suite | [development](development.md#3-checks) |
| `nginx.conf`, `Dockerfile` | Same-origin proxy and image | [architecture](architecture.md#4-nginx), [deployment](deployment.md) |
