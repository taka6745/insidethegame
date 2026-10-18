# Demo ETL contracts

| Endpoint | Purpose |
| --- | --- |
| `GET /demo/recording` | Exact source JSON bytes; hash identifies the loaded match |
| `POST /demo/snapshots` | Publish recording prefix from metadata and cursor |
| `POST /demo/viewer-snapshots` / `/demo/question-snapshots` | Same operation; compatible consumer routes |
| `GET /demo/snapshots/{id}` | Read published canonical snapshot for narrative stub |
| `POST /graphql` | Read standard stats or filtered, paginated historical events |

A publication body contains `snapshot`, `teams`, `players`, `data_reference`; `events` is omitted. The ETL materialises its own recording prefix and verifies the content hash. Metadata includes run ID, recording hash, cursor, football clock and period. Old snapshots remain readable when newer runs begin, but never see later deliveries. `/dev/*-snapshots` accepts full payloads only for compatibility tests.

GraphQL `questionData(snapshotId, operation: "stats" | "events", offset, limit, start, end, eventType, playerId, period)` preserves the backend contract. `limit` is 1–100; time ranges are start-inclusive/end-exclusive. Each response identifies its exact snapshot and match. `matchState`/`matchEvents` retain older local read compatibility.

Stat IDs are `<team-id>:<metric>` or `all:<metric>`. Metrics include goals, shots, passes, corners, cards, saves, tackles, interceptions, fouls, pass accuracy and possession. The recording's capabilities determine availability. The GRF adapter represents a scored attempt once as `goal`; total attempts count non-scoring `shot` records plus goals. Native shot contacts remain in the raw capture. Unknown pass outcomes are excluded from accuracy; unavailable shot outcomes do not produce a fabricated on-target count. Ownership samples exclude unowned-ball time and are cut off at the observed video position.

The original recording is retained for provenance. Only observed events are exposed by snapshot queries. No generation, random stat fabrication or user-specific calculation runs in this service.
