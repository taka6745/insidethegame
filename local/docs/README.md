# Local integration documentation

> **In short:** how the local stack is wired, what its checks prove, how demo control runs the demo and its seeds, and how to fix the usual problems.

| | |
| --- | --- |
| **Code** | `compose.yaml`, `demo_control.py`, check scripts, `settings.py`, `config/`, `sql/`, env examples |
| **Contracts** | [contracts/README.md](../contracts/README.md): every cross-service boundary |

```
docs/
├── README.md               this index
├── overview.md             what runs, profiles
├── architecture.md         topology, ports, Docker names
├── components/
│   ├── demo-control.md     demo operator: start, cancel, skip, status, seeds
│   ├── checks.md           integration checks and pipeline probes
│   └── config.md           compose, emulator config, settings, env files
├── development.md          machine, troubleshooting, licences, coverage limits
├── deployment.md           demo control on Azure
└── decisions.md            why the stack looks like this
```

Component pages are by concern, not one per folder: `sql/` and `no-media/` are covered in config.md. No `design/` material exists.
