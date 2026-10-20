# Demo ETL contracts

| Endpoint | Purpose |
| --- | --- |
| `GET /demo/recording` | Exact source JSON bytes; hash identifies the loaded match |
| `POST /demo/snapshots` | Publish recording prefix from metadata and cursor |
| `POST /demo/viewer-snapshots` / `/demo/question-snapshots` | Same operation; compatible consumer routes |
| `GET /demo/snapshots/{id}` | Read published canonical snapshot for narrative stub |
| `POST /graphql` | Read standard stats or filtered, paginated historical events |

HTTP publication is available only in fixture mode. Broker mode returns 409 for all publication routes.

A publication body contains `snapshot`, `teams`, `players`, `data_reference`; `events` is omitted. The ETL materialises its own recording prefix and verifies the content hash. Metadata includes run ID, recording hash, cursor, football clock and period. Old snapshots remain readable when newer runs begin, but never see later deliveries. `/dev/*-snapshots` accepts full payloads only for compatibility tests.

GraphQL `questionData(snapshotId, operation: "stats" | "events", offset, limit, start, end, eventType, playerId, period)` preserves the backend contract. `limit` is 1–100; time ranges are start-inclusive/end-exclusive. Each response identifies its exact snapshot and match. Event items carry `sequence`, `video_seconds`, `x`, `y`, `possession_id` and every source qualifier in `qualifiers` (source names, e.g. `endX`, `shotOutcome`); v2 recordings leave them null/empty. Snapshot IDs and `GET /demo/snapshots/{id}` exclude these detail fields, so v2 producers and the narrative stub keep computing the same digest; read them through GraphQL.

**Broadcast clock (v3).** Stoppage time repeats clock values: first-half events can reach 48:00 in period 1 while period 2 restarts at 45:00. Items are ordered by `(period, match_time_seconds, delivery order)`; pass `period` with `start`/`end` to select one half. A snapshot's clock must equal its latest event by `(period, time)`, except once the whole recording is released: the producer may then declare any final clock in that or a later period (e.g. `5400`, period 2). `matchState`/`matchEvents` retain older local read compatibility.

Stat IDs are `<team-id>:<metric>` or `all:<metric>`. Metrics include goals, shots, passes, corners, cards, saves, tackles, interceptions, fouls, pass accuracy and possession. The recording's capabilities determine availability. The GRF adapter represents a scored attempt once as `goal`; total attempts count non-scoring `shot` records plus goals. Native shot contacts remain in the raw capture. Unknown pass outcomes are excluded from accuracy; unavailable shot outcomes do not produce a fabricated on-target count. Ownership samples exclude unowned-ball time and are cut off at the observed video position.

The original recording is retained for provenance. Only observed events are exposed by snapshot queries. No generation, random stat fabrication or user-specific calculation runs in this service.

Opta-style v3 ([contract](../../data-generation/docs/opta-events.md)) adds `clearances`, `take_ons`, `successful_take_ons`, `aerials_won` and `ball_recoveries` (each available when its type is supported) plus `blocked_shots`; with `shot_outcomes`, `shots_on_target` is goals plus `saved` shots and `blocked_shots` counts the team's own blocked attempts. `post` and `off_target` are neither. Recordings may hold up to 16 MiB and 100,000 events.

Native v2 adds capability-gated metrics for fouls won, offsides, throw-ins, free kicks, goal kicks, kick-offs, penalties taken and keeper claims. Restart records count executions; their accompanying pass/shot records count the action separately. Whistled fouls exclude offsides and companion `foul_won` records. Unsupported channels remain unavailable, even when no matching event appears. See the [event coverage guide](../../data-generation/docs/event-coverage.md).

`headed_passes`, `headed_shots` and `headed_contacts` require declared body-part coverage for every contributing event category. Headed shots include goals in the native contract. If any goal has unknown body part, complete headed-shot totals are unavailable; known headed contacts alone do not establish complete contact coverage.

Broker input on `match-events` is `{type: "MatchEvent", version: 1, snapshot: <metadata>, event: <canonical event or null>}`. The nested metadata contains the existing snapshot watermark, catalogues, data reference and `events: []`. A non-null event must agree with the recording delivery at `cursor - 1` on every field it states; a producer may omit the v3 fields (`sequence`, `video_seconds`, `x`, `y`, `possession_id`, `qualifiers`), which ETL takes from its own recording. Null permits initial/recovery publication. After durable storage, `match-notifications` receives `{type: "MatchSnapshotReady", version: 1, snapshot: <same metadata>}`. The notification does not contain history; consumers fetch it via GraphQL.
