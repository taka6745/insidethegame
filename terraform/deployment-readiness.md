# From the local demo to Azure

**Not deployed.** The working viewer uses Event Hubs and Service Bus emulators for live delivery, plus separate GraphQL demo services for reads. Terraform validates a foundation with mocks; it does not currently deploy the app.

```text
Today:   recording → ETL demo → GraphQL → one backend → viewer
Cloud:   Event Hubs → ETL / calculation owner → shared delivery → viewers
                         narrative service → Service Bus ─────┘
```

| Before an Azure release | Required change / evidence |
| --- | --- |
| Runtime placement | Add actual Container Apps images, registry access, probes, internal service addresses and budgets. Keep the current backend at one replica and one worker; it has process-local replay, calculations and socket ownership. |
| Data access | Complete private endpoints/VNet routes and private DNS for SQL, both Cosmos accounts and PostgreSQL. Add managed identities/RBAC, credential rotation and protected Terraform state. Public access remains disabled. |
| Live ingestion | SDK consumers and durable-before-ack handling are implemented for the demo. Add persistent Event Hubs partition checkpoints/ownership, replace recorded-prefix ETL recovery, and validate Azure retention, lock expiry and dead-letter operations. |
| Upstream services | Replace demo PostgreSQL ETL stores with Azure SQL history and Cosmos stats adapters; complete Stream Analytics. Replace authored SQLite narrative storage with the narrative service's intended implementation. |
| Demo assets | Package or securely mount the immutable GRF event recording; the local host bind mount does not travel with the ETL image. Mount durable storage if retaining the SQLite stub for an Azure demo. Serve video through media storage/CDN; do not stream it through backend replicas. |
| Frontend proxy | Configure `BACKEND_UPSTREAM` and `NGINX_RESOLVER` for the actual network. Docker DNS is not an Azure resolver. Use authenticated ingress/TLS and an explicitly secured upstream route. |
| Agents and access | Configure Foundry deployments and model credentials/identity. Replace selectable demo identities with authentication/authorization; disable demo reset/upload controls. Bound question queues, model concurrency and per-account quotas. |
| Multiple replicas | Add fenced match ownership, shared session takeover, durable subscription/outbox delivery and reconnect cursors before raising the replica count. Validate kill/restart and duplicate-delivery recovery. |

Container Apps supports autoscaling, but it does not make application state distributed. Algorithm benchmarks are separate from viewer capacity: load-test fan-out, reconnect bursts, database connections and question/model throughput. See [scaling boundaries](../user-backend/docs/scaling.md).

**Local tools:** Microsoft's emulators need no Azure account, but have service-specific limitations and accepted licence terms. LocalStack for Azure is optional and not configured here; it requires an auth token and Azure access on a LocalStack account. Its Terraform endpoint is separate from real Azure. Do not substitute emulator success for cloud identity, networking, durability or capacity tests.

Sources checked 2026-10-19: [Container Apps scaling](https://learn.microsoft.com/en-us/azure/container-apps/scale-app), [Event Hubs emulator](https://learn.microsoft.com/en-us/azure/event-hubs/overview-emulator), [Service Bus emulator](https://learn.microsoft.com/en-us/azure/service-bus-messaging/overview-emulator), [LocalStack Azure authentication](https://docs.localstack.cloud/azure/getting-started/auth-token/), [LocalStack Terraform](https://docs.localstack.cloud/azure/connecting/infrastructure-as-code/terraform/).
