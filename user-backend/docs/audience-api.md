# Audience definitions API

**The backend stores configuration. The narrative engine does the writing.** This endpoint returns no viewer records and never calls a model.

```text
Backend Postgres → GET audience-config → Narrative engine
                                           ↓
Frontend ← Backend routing ← Service Bus bucketed versions
```

## Read from the narrative engine

```sh
curl -i http://localhost:18000/matches/synthetic-demo/audience-config
```

From the Docker network use `http://backend:8000`. The [API explorer](http://localhost:18000/docs) includes the response schema.

| Response field | Meaning |
| --- | --- |
| `schema_version` | Wire contract version; currently `1` |
| `match_id`, `revision` | Match and exact configuration revision |
| `layers` | Layer IDs/descriptions and their available options/descriptions |
| `buckets` | Explicit combinations with stable IDs and `enabled` flags |
| `generation_targets` | Every enabled combination, with selected descriptions expanded for the model |

The initial IDs match existing routing, such as `home:analytical`. Twelve combinations are [seeded](../fixtures/audiences.json); configuration is stored in `audience_catalog` in Match App PostgreSQL. Restarting does not reset edits. The endpoint returns a single consistent revision. Old experimental `audience_config` and framing-cache tables are not used.

Fetch before each shared narrative-generation cycle. Keep the response's `ETag` and send `If-None-Match` next time; **304** means reuse that cached response. On an error, do not interpret it as an empty catalogue. The narrative orchestrator must explicitly decide to retry or continue using its last valid revision. That orchestration is still to build.

Pass each target's layer/option descriptions to the narrative author as data, alongside the neutral source. Generate for **all `generation_targets`**, regardless of viewer presence. Empty targets means generation is paused. Configuration edits do not trigger model calls or regenerate history. Retain the revision used with each generation batch so changes can be traced.

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

To shorten a demo, set unwanted buckets' `enabled` to `false`, or remove them. Add layers/options and explicitly define their combinations; there is no automatic Cartesian expansion. Bounds are 8 layers, 20 options per layer and 48 combinations. These keep configuration/model inputs bounded and can be revised deliberately.

**Current integration limit:** the API supports additional dimensions, but the viewer/narrative transport harness still uses the original `team` and `fan_style` fields. New dimensions require the narrative publisher and viewer-selection contract to be extended before those new combinations can be delivered. No framing runs in the backend.
