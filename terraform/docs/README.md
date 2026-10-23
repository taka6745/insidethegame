# Azure infrastructure documentation

> **In short:** how the stack is laid out on Azure, how to deploy and remove it, how the spend guard protects the credit, and what a production release still needs.

| | |
| --- | --- |
| **Code** | `terraform/*.tf` (app stack), `guard/`, `azure/` (`./dev azure`), `tests/` |
| **Other stacks** | `etl/infra`, `narrative-engine/infra`, `data-generation/infra` (each documented in its service) |

```
docs/
├── README.md            this index
├── overview.md          the five stacks, resource groups, status
├── architecture.md      request and data paths
├── components/
│   ├── guard.md         spend guard: budgets, last resort, Stream Analytics schedule
│   └── azure.md         ./dev azure: toolbox image, media upload, tests
├── development.md       checks without Azure
├── deployment.md        up, down, demo URL, quota, cost
└── decisions.md         choices and production gaps
```
