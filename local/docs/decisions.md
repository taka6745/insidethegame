# Decisions

> **In short:** why the local stack and the demo operator look as they do.

| | |
| --- | --- |
| **Contracts** | Agreed in [contracts/README.md](../contracts/README.md) before producers and consumers change |

| Decision | Why |
| --- | --- |
| Microsoft emulators, not LocalStack | Account-free; same SDKs and names as Azure |
| The feed is an external provider with its own Postgres and network | Our services see it only through Event Hubs and HLS over HTTP |
| Demo control lives outside the product services | No product service learns about the others; a release can drop it |
| Seeds are recorded on the pipeline, then restored through demo-only adapters | Nothing past a start point can exist; core services never branch on a demo |
| Skip ahead moves run clocks rather than chaining seeds | No new matchIds, any target; follows and sessions carry on |
| One demo-control replica | Start and cancel never interleave without a distributed lock |
| Purge owners defined once (`demo_control.OWNERS`) | The probes purge the same consumers |
