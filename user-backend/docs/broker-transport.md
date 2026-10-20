# Local broker transport

```text
recorded replay ── Event Hubs ──┬── backend custom index ── viewer
                               └── ETL stub
                                     │ committed snapshot readiness (Service Bus)
                               narrative stub
                                     │ bucket narratives (Service Bus)
                               durable backend inbox ── viewer

Backend reads: ETL GraphQL (stats/history), narrative GraphQL (recaps).
```

**Implemented locally, not deployed.** `ACCEPT_EULA=Y ./dev up backend` starts the actual Microsoft emulators and Azure Python SDK adapters. No Azure/LocalStack account is required. HTTP snapshot POSTs return 409 in broker mode. Local stubs, selectable demo profiles and loopback-only access remain intentional.

| Message | Contract / ordering |
|---|---|
| `MatchEvent` v1 | `snapshot` holds the existing metadata wrapper with empty `events`; `event` holds one canonical event. Partition key is the match ID. ETL and backend use separate consumer groups. |
| `MatchSnapshotReady` v1 | ETL sends snapshot metadata after both history and standard stats are committed. A retry republishes readiness idempotently. |
| `BucketNarratives` v1 | Snapshot watermark, already-framed `items`, event context and audience revision. Narrative history is archived before publish. Backend saves the inbox before completing the message. |

The backend replay producer waits for its shared Event Hubs consumer to commit the next event before advancing. Consumers preserve IDs, revisions and corrections. Old-run events do not change the active calculation index; duplicates do not increment it. Live narrative reads use an exact snapshot ID and monotonic audience revisions, preventing mixed-cursor presentation. Questions only wait/read; they cannot publish replay events or request narrative generation.

Initial, reset and full-time **recovery watermarks** carry `event:null`. These cannot advance backend calculations. The ETL stub validates them against its immutable recording and materializes the prefix; the future incremental ETL will replace this demo behavior. The producer remains inside the removable lab adapter for the hackathon. Production should run independently of viewer API processes.

Narrative audience polling refreshes the last committed snapshot every 2 seconds and sends only changed output. An explicit duplicate readiness notification resends output, allowing recovery after disposable emulator messages disappear. Earlier watermarks retain neutral history without moving live polling backwards.

## Recovery limits

- Backend event cursor/calculation values and narrative inbox persist in PostgreSQL. Narrative archive/poll target persist in its SQLite volume.
- Event Hubs consumers restart from retained beginning; they have no durable partition checkpoint store or distributed lease. The single backend rehydrates its observed prefix and skips committed deliveries. Keep one worker/replica.
- Service Bus transient persistence/publication failures retry under a renewable lock for up to five minutes; expired locks return to broker redelivery. Extended repeated outages can still exhaust delivery counts. Monitor/replay dead letters before any production release.
- The integration checks use isolated runs, then republish the viewer's current watermark. Broker tests are not a load benchmark. Stubs still use PostgreSQL/SQLite instead of Azure SQL/Cosmos and do not implement ASA or AI narrative generation.

Run `./dev test backend` for API regressions plus real AMQP integration. The check verifies an event and duplicate, full-match GraphQL snapshots, Service Bus delivery, an isolated real-PostgreSQL custom index/inbox and disabled HTTP snapshot writes. [Azure deployment work](../../terraform/deployment-readiness.md).
