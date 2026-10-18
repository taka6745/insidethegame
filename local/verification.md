# Verified locally — 2026-10-18

Machine: Apple Silicon macOS, Docker Engine 29.7.2, Compose 5.5.1. Existing unrelated containers were left running.

| Check | Result |
| --- | --- |
| `./dev up` + `./dev test` | Passed: Postgres profiles/two databases and Cosmos document round trip. |
| `ACCEPT_EULA=Y ./dev up azure` | Started: Event Hubs, Service Bus, SQL Server, Azurite and Data API builder. Licence acceptance explicitly authorised by the local user. |
| `./dev test azure` | Passed: SDK event send/receive, both Service Bus topic deliveries, SQL fixture seed and GraphQL history query. |
| `./dev replay` | Published the three synthetic fixture events successfully. |
| `./dev terraform check` | Passed: formatting, Azure provider schema validation and one mocked plan test with four boundary assertions. No Azure account or deployment. |
| Guide checks | Local Markdown links checked; SVG rendered and visually inspected. |

These checks exercise actual local containers. They do **not** validate the Stream Analytics job, real Foundry models, application services, frontend, generated-code isolation or a cloud deployment. Terraform's mock-provider checks are also separate from runtime integration.

Re-run the commands on a new machine. Emulator behaviour differs from Azure; in particular messages/state, identity, throughput and resource-management APIs are not cloud-equivalent.
