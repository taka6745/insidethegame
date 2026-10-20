# Transport

> **In short:** how messages get in and narratives get out. `servicebus.py` listens to the ETL and presence topics and publishes to `narratives`; `files.py` does the same with JSONL files so a whole match can be replayed locally.

| | |
| --- | --- |
| **Status** | Implemented · tested · deployed |
| **Code** | [`narrative_engine/transport/`](../../narrative_engine/transport/): `servicebus.py`, `files.py` |
| **Topics** | In: `match-notifications` (sub `narrative-engine`), `presence` (sub `narrative-engine`). Out: `narratives` |
| **Auth** | Shared access keys scoped to listen or send (LATER: managed identity) |
| **Tests** | `test_servicebus.py` |

## 1. Receiving (`SubscriptionListener`)

*In short: complete fast, abandon on failure, dead-letter what can't be read.*

| Outcome | Action |
| --- | --- |
| Handler returned | Complete. The handler only records the message in the checkpoint, so this takes milliseconds |
| Handler raised | Abandon; Service Bus redelivers, and dead-letters after 10 deliveries |
| Body is not JSON | Dead-letter at once (`unreadable`) |
| Lock lost while settling | Logged as a warning; redelivery is harmless because recording is idempotent |

The message type comes from the body's `messageType`, or is fixed (`PresenceChanged`) for the presence topic. Locks are auto-renewed as a safety net.

## 2. Publishing (`ServiceBusPublisher`)

*In short: one message per narrative, safe to repeat.*

- Body: the narrative document ([contracts](../../contracts/README.md#output-2-service-bus-live-narratives)).
- `MessageId` = narrative `id`; the topic's duplicate detection (10 minutes) drops repeats.
- Application properties `userType` and `matchId` for subscription filters.
- The sender is opened once under a lock before the first send, which avoids an SDK race when many buckets publish at once.

## 3. Files (`files.py`)

*In short: the local equivalents.*

| Piece | Local role |
| --- | --- |
| `read_notifications` / `replay` | Feed an ETL notifications JSONL into a handler, as fast as possible or paced to the recorded timing |
| `JsonlSink` | Append narratives to `.local/narratives.jsonl` |
| `MemorySink` | Keep published narratives in memory (tests) |
| `narrative_doc` / `narrative_from_doc` | The one serialisation of a narrative, shared by files, Cosmos and Service Bus |
