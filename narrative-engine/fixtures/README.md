# Recorded-match commentary

Bound to the 90-minute Chelsea 2–1 Manchester United GRF recording (seed 37; [event contract](../../data-generation/docs/opta-events.md)): 92 broadcast minutes × 12 buckets, 24 tier recaps and 10 key moments, schema v2. Prose was fact-checked against the events by independent reviewers.

Demo content authored offline by AI agents from the canonical events and video contact sheets, then checked against the events in review passes. It is not runtime LLM output or an actual Premier League result. The runtime releases only what the viewer's snapshot has already observed.

```text
commentary-text.json (authored prose) + ETL canonical export
        → tools/bind_commentary.py --reviewed-hash <sha256>
        → grf-narratives.json (schema v2; adds release, evidence, digests)
```

## Authored input: `commentary-text.json`

```jsonc
{
  "provenance": { ... },
  "minutes": {                      // exactly every broadcast minute of the recording
    "p1-m1":  { "recap": "neutral minute recap",
                "narratives": { "home:simple": "…", /* all 12 bucket IDs */ } },
    "p1-m47": { ... },              // 45+2' (first-half stoppage)
    "p2-m46": { ... }               // 46' (second half restarts at 45:00)
  },
  "tiers": [                        // children listed before parents; contiguous, same period
    { "id": "p1-t5-1", "tier": "five-minute", "child_ids": ["p1-m1", "…", "p1-m5"], "summary": "…" },
    { "id": "p1-half", "tier": "half", "child_ids": ["p1-t20-1", "p1-t20-2", "p1-t5-9", "p1-m46", "…"], "summary": "…" }
  ],
  "key_moments": [
    { "id": "km-…", "rank": 1, "title": "…", "summary": "…", "event_ids": ["…"],
      "start_video_seconds": 1290.0, "end_video_seconds": 1302.5 }
  ]
}
```

Minute IDs are `p{period}-m{minute}`; `minute` is the 1-based broadcast minute (`timeMin + 1`), so stoppage stays in its own period. Every minute from the period's first to the one containing its `period_end` is required, even when empty. Tier values: `five-minute`, `ten-minute`, `twenty-minute`, `half`. Ranks are unique across the match; key-moment IDs must not reveal the rank.

## Bound output: `grf-narratives.json`

```jsonc
{
  "schema_version": 2, "recording_hash": "<sha256 of recording.json bytes>", "synthetic": true,
  "provenance": { ... },
  "minutes": [{
    "id": "p1-m47", "period": 1, "minute": 47, "label": "45+2'", "start_seconds": 2760, "end_seconds": 2820,
    "release": { "cursor": 5702, "period": 1, "clock_seconds": 2820, "video_seconds": 2702.4, "prefix_digest": "<sha256>" },
    "evidence": [ /* canonical ETL events: goals so far + this minute's decisions */ ],
    "recap": "…",
    "narratives": [{ "bucket_id": "home:simple", "text": "…", "stat_ids": ["chelsea:goals", "…"] }]
  }],
  "tiers": [{ "id": "…", "tier": "half", "period": 1, "start_seconds": 0, "end_seconds": 2940,
              "child_ids": ["…"], "summary": "…", "release": { ... } }],
  "key_moments": [{ "id": "…", "rank": 1, "title": "…", "summary": "…", "event_ids": ["…"],
                    "period": 1, "minute": 5, "label": "5'", "start_video_seconds": 275.0, "end_video_seconds": 290.0,
                    "release": { ... }, "evidence": [ /* the cited events */ ] }]
}
```

| Unit | Released at |
| --- | --- |
| Minute | First delivery after the minute: a later clock in its period, a later period, or its `period_end` |
| Tier | Its last child's release; also needs every child intact |
| Key moment | All its events delivered and video passed `end_video_seconds` |

A unit is hidden unless the snapshot reaches its cursor and `(period, clock)`, the recording hash matches, its delivery prefix digest is unchanged and its evidence has no later correction. `narrative_demo/models/fixtures.py` is the executable schema.

Before binding, review **all** prose against the event evidence; the binder checks structure and timing, not natural-language claims. Names are illustrative simulator slots with generic abilities.
