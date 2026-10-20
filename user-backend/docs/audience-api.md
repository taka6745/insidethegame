# Audience definitions API

**The backend stores configuration. The narrative engine does the writing.** This endpoint returns no viewer records and never calls a model.

```text
Backend Postgres → GET audience-config → Narrative engine
                                           ↓
Frontend ← Backend routing ← Service Bus bucketed versions
```

## Read from the narrative engine

```sh
curl -i http://localhost:18000/matches/product-demo-match/audience-config
```

From the Docker network use `http://backend:8000`. The [API explorer](http://localhost:18000/docs) includes the response schema.

| Response field | Meaning |
| --- | --- |
| `schema_version` | Wire contract version; currently `1` |
| `match_id`, `revision` | Match and exact configuration revision |
| `layers` | Layer IDs/descriptions and their available options/descriptions |
| `buckets` | Explicit combinations with stable IDs and `enabled` flags |
| `generation_targets` | Every enabled combination, with selected descriptions expanded for the model |

The stable configuration IDs use match-relative sides, such as `home:analytical`. Publish those target IDs verbatim; product snapshots expose the selected canonical `bucket_id`. Twelve combinations are [seeded](../fixtures/audiences.json) for the loaded match; configuration is stored in `audience_catalog` in Match App PostgreSQL. For compatibility, the viewer also accepts the older prewritten fixtures' actual-team IDs. The endpoint returns a single consistent revision. Old experimental `audience_config` and framing-cache tables are not used.

Fetch before each shared narrative-generation cycle. Keep the response's `ETag` and send `If-None-Match` next time; **304** means reuse that cached response. On an error, do not interpret it as an empty catalogue. The narrative orchestrator must explicitly decide to retry or continue using its last valid revision. That orchestration is still to build.

Pass each target's layer/option descriptions to the narrative author as data, alongside the neutral source. Generate for **all `generation_targets`**. For the product viewer, these are the union of combinations with a connected viewer, so the hackathon avoids unused generation. Empty targets means generation is paused. Retain the revision used with each generation batch so changes can be traced.

## Viewer choices

`PUT /product/TOKEN/audience` accepts `{"team":"away","fan_style":"experienced"}` and returns the updated session and snapshot. Team accepts `home`, `away`, `neutral`; style accepts `analytical`, `simple`, `casual`, `experienced`. Choices persist per profile/match run, separately from account defaults. Changing them keeps questions and pins, reroutes existing narrative history and updates default stat cards immediately.

All twelve definitions remain in the database. Product WebSocket attach, detach, takeover and selection changes update their `enabled` flags; event delivery and session polling do not write presence. Multiple viewers sharing a combination keep one target enabled until the last one disconnects. Merely creating a session does not activate generation. Restart clears abandoned product flags; replay reset closes old viewers. Definitions and semantic descriptions survive.

If presence publication temporarily fails after a choice is saved, the API still returns that saved choice and the shared update loop retries. A continued outage closes live connections for reconnection. A generator must handle catalogue errors as unavailable, not as permission to generate all buckets.

This uses the existing **single-process demo owner**. Socket disconnect detection can take the transport heartbeat timeout. Multiple backend replicas need shared expiring presence leases before using this policy. The separate `synthetic-demo` profile harness keeps its manually enabled catalogue. Use the actual match ID from the product snapshot, not that harness ID.

The fake narrative service serves prewritten fixtures without model calls, including existing history for all twelve buckets. The future narrative generator must read `generation_targets` before each batch. Changing selection does not launch generation or invent missing historical framing.

## Edit the local demo

Only the development API accepts writes (`ENABLE_DEV_FEED=1`); the narrative-facing endpoint is read-only. This demo uses the existing loopback-only, unauthenticated local setup. Add service authentication before exposing it beyond local development.

`PUT /dev/matches/synthetic-demo/audience-config` takes:

```json
{
  "expected_revision": 1,
  "config": {
    "layers": [
      {"id":"team", "description":"Match allegiance",
       "options":[{"id":"home", "description":"Supports the home team; keep facts balanced."}]},
      {"id":"fan_style", "description":"Explanation style",
       "options":[{"id":"simple", "description":"Use short sentences and explain football terms."}]}
    ],
    "buckets": [
      {"id":"home:simple", "selections":{"team":"home","fan_style":"simple"}, "enabled":true}
    ]
  }
}
```

This replaces the catalogue with one demo combination. Normally copy the current layers and buckets from GET, then edit them. Use the current revision. Success returns the new revision; a concurrent edit returns **409**. Unknown options, missing layer selections, duplicate IDs or duplicate combinations return **422** without changing the database.

The standalone profile harness allows manual `enabled` flags. Product flags are owned by viewer presence. Add layers/options and explicitly define their combinations; there is no automatic Cartesian expansion. Bounds are 8 layers, 20 options per layer and 48 combinations. These keep configuration/model inputs bounded and can be revised deliberately.

**Current integration limit:** the API supports additional dimensions, but the viewer/narrative transport harness still uses the original `team` and `fan_style` fields. New dimensions require the narrative publisher and viewer-selection contract to be extended before those new combinations can be delivered. No framing runs in the backend.
