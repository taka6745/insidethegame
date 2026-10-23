# Narrative engine contracts

> **In short:** what the user backend (and demo control) can rely on: history over GraphQL, live narratives and clips on Service Bus, targets and prompts read from the backend, and the admin purge plus the demo-only seed routes.

| | |
| --- | --- |
| **Status** | Implemented · tested ([overview](../docs/overview.md)) |
| **Outputs** | GraphQL history · Service Bus `narratives` (bucket narratives, follow narratives, `FollowClip`, `MomentClip`) |
| **Inputs** | ETL notifications and GraphQL · backend audience targets, prompts, policy, subscription targets |
| **Admin** | `POST /admin/matches/purge` always; `POST /admin/matches/export` and `/restore` only with `DEMO_SEEDS=1` |

What the user backend can rely on. Live narratives arrive on Service Bus; this GraphQL API serves history for joins and reconnects. Inputs come from the [ETL contracts](../../etl/contracts/README.md): SPADL actions (Output 3), the SPADL stat catalogue (`executeStatsAtSeq`) and the trend indicators (`executeTrendsAtSeq`, `executeTrendSpellsAtSeq`, [local contracts §4b](../../local/contracts/README.md#4b-trend-definitions)), read at the step's canonical seq, plus key events, MA1 and MA3.

## Output 1: GraphQL (narrative history, read-only)

**Implemented** ([api.py](../narrative_engine/api.py)). On Azure (`./dev azure up`) it is on the engine's internal ingress at `/graphql`, reachable only inside the Container Apps environment (the user backend); anonymous read there. Local stack: `127.0.0.1:18012`. Offline: `python -m narrative_engine.api .local/narratives.jsonl` or `python -m devtools.local <notifications> --serve 8000`, then `http://localhost:8000/graphql`.

| Query | Returns | Use |
| --- | --- | --- |
| `narratives(matchId, userType, afterSeq = 0, first = 50)` | One bucket's narratives with `seq > afterSeq`, oldest first, plus `hasNextPage` and `endCursor` (the last `seq`) | Backlog on join; gap fill on reconnect |
| `matchState(matchId)` | `status` (`live`/`complete`), `lastSummarised` match time, `activeUserTypes` | Which buckets are being written for; whether the match is over |
| `storylines(matchId)` | The match's storylines in the order they opened: `id`, `label` (the analyst's words), `team` (contestant id or null), `status` (`active`, `dormant`, `resolved`), `salience`, `openedAt`/`updatedAt`/`resolvedAt`, `outcome`, `beats` (`at`, `headline`, `explanation`, `confidence`, `analysisId`), `keyEventIds` (ETL `keyEvents` ids, linked by rule) | Story follows; "the story so far" |
| `subscriptionNarratives(matchId, topicId, userType, afterSeq = 0, first = 50)` | One followed topic's narratives for one bucket, same paging as `narratives`, plus `topicId` and `decision { score confidence novelty model }` (null for `catchUp`). A malformed `topicId` is an error | Gap fill for follow narratives |
| `contextBlocks(matchId, includeSuperseded = true)` | The match's neutral context summaries in match order: `tier` (`minute`, `five-minute`, `twenty-minute` for an earlier block, `half` for a closed period's single block), `level` (0, 1, 2), `coversFrom`/`coversTo`, `summary`, `supersededBy` | Question and replay recaps; only minutes the engine has already processed exist |

```graphql
query ($m: String!, $u: String!, $after: Int!) {
  narratives(matchId: $m, userType: $u, afterSeq: $after, first: 50) {
    items { id seq eventSeq stepId triggerType triggerReason matchTime { periodId timeMin label } text createdAt }
    hasNextPage endCursor
  }
  matchState(matchId: $m) { status activeUserTypes }
}
```

- **`userType`** is a bucket id from the user backend's audience catalogue (for example `home:analytical`). A malformed id is a GraphQL error, as is `first` outside 1–200.
- **`eventSeq`** is the canonical `MatchEvent` seq of the newest data the narrative was written from (MA3 `eventSeq` of the key event's own row for a key-event step, else of the latest row up to its horizon; [snapshot identity](../../local/contracts/README.md#1-identity-and-snapshots)). Show a narrative at snapshot `(matchId, s)` only when `eventSeq ≤ s`. `null` when no MA3 row precedes it.
- **`seq`** counts 1, 2, 3… per match and bucket, with no gaps. Keep the last `seq` you showed per bucket; on reconnect, ask for `afterSeq` = that value. Following `endCursor` while `hasNextPage` gets everything.
- **`stepId`** is shared by every bucket's version of one narrative step (a goal, half time, a scheduled update). `id` is unique and stable: `narr:{matchId}:{userType}:{seq}`.
- **`matchTime`** uses the ETL's Opta clock (`periodId`, 0-based `timeMin`) and its broadcast `label` (`45+2'`). A bucket only gets narratives while it is in `activeUserTypes` (enabled in the backend's config; steps already queued when it is disabled still finish). A bucket enabled mid-match, or re-enabled, gets a `catchUp` narrative, then continues with the rest.
- **`storylineIds`** lists the storyline the narrative advances (its step's focus, the same for every bucket; empty when the match has none yet) and **`analysisId`** the match analysis it read (`null` before the first). A `storylineTurn` step is written when an analysis opens or resolves a storyline.
- `text` is plain text, one or two sentences. Stat selection belongs to the user backend.
- **`timeSec`** is the second of `matchTime` the step's data reaches (59 for scheduled steps; a half-time or full-time step uses the End event's own clock and second, and is written as soon as `PeriodEnded` arrives); **`audienceRevision`** is the backend audience revision the bucket came from; **`promptVersion`** is `{role}@{version}` from the prompts API (tests and devtools: the shipped file name, `narrative-author.v7`). **`model`** is the Azure AI Foundry deployment that answered, or `local-model` on the local stack.

## Output 2: Service Bus (live narratives)

**Implemented.** Topic `narratives` in the ETL's Service Bus namespace (`narrative-engine/infra`), subscription `user-backend`. One message per narrative, written to Cosmos DB before it is sent. The body is the narrative document below (as in local `.local/narratives.jsonl`), with `MessageId` = `id` (the topic has duplicate detection) and application properties `userType` and `matchId` for subscription filters.

```json
{"id": "narr:demo:away:casual:3", "matchId": "demo", "userType": "away:casual", "seq": 3, "eventSeq": 812,
 "stepId": "demo:key:2700000390",
 "trigger": {"type": "keyEvent", "ref": "key:2700000390", "reason": "Key event at 24' (23:09): Goal for Riverside FC, Mensah", "eventIds": []},
 "matchTime": {"periodId": 1, "timeMin": 23, "label": "24'"},
 "text": "...", "model": "gpt-6.1-sol", "promptVersion": "narrative-author@7", "tokens": {...}, "createdAt": "2026-10-18T21:07:02+00:00",
 "analysisId": "analysis:demo:1-019", "storylineIds": ["sl:demo:2"]}
```

Delivery is at least once; deduplicate on `id`. If a `seq` is skipped, fill the gap from GraphQL.

### Follow narratives (`kind: subscription`)

**Implemented ([follows](../docs/components/follows.md)); the backend accepts it.** Same topic, same document, plus `kind`, `topicId` and `decision`; application properties add `kind` (`bucket` on bucket narratives). One narrative per triggered topic **per bucket of its followers** (generation shared by every follower in that bucket; the backend delivers per subscription). Bucket narratives carry `kind: "bucket"` (or omit it).

```json
{"id": "sub:demo:topic:3fa2c1d0e4b5a697:home:analytical:2", "kind": "subscription", "topicId": "topic:3fa2c1d0e4b5a697",
 "matchId": "demo", "userType": "home:analytical", "seq": 2, "eventSeq": 812, "stepId": "demo:sub:topic:3fa2c1d0e4b5a697:key:2700000390",
 "trigger": {"type": "keyEvent", "ref": "key:2700000390", "reason": "...", "eventIds": []},
 "decision": {"score": 2.6, "confidence": 0.71, "novelty": 0.83, "model": "microsoft-decision-1"},
 "matchTime": {"periodId": 1, "timeMin": 23, "label": "24'"}, "timeSec": 9,
 "text": "...", "model": "gpt-6.1-sol", "promptVersion": "subscription-author@1", "tokens": {...},
 "createdAt": "...", "storylineIds": ["sl:demo:2"]}
```

- `id` = `sub:{matchId}:{topicId}:{userType}:{seq}`; `seq` counts 1, 2, 3… per (topic, bucket) with no gaps.
- `trigger.type`: `keyEvent`, `scheduled` (a minute recap), `storylineTurn` (an analysis update), `halfTime`, `fullTime`, or `catchUp` ("the story so far", written once when a (topic, bucket) pair first appears in the targets).
- `eventSeq` bounds it exactly as for bucket narratives. The backend drops narratives of a topic it does not know (never followed, or purged).

### Follow clips (`type: FollowClip`)

**Implemented.** Same topic. One message per (topic, key event) whose decision verdict carries `clip` (below), sent before and apart from that topic's narratives, so a narrative dropped as ungrounded never loses the moment's clip. Re-sent on a step retry; `MessageId` = `id`; application properties `matchId` and `kind: "clip"` (no `userType`: a clip belongs to the topic, not a bucket).

```json
{"type": "FollowClip", "id": "clip:demo:topic:3fa2c1d0e4b5a697:2700000390", "matchId": "demo",
 "topicId": "topic:3fa2c1d0e4b5a697", "eventId": 2700000390, "eventSeq": 812,
 "stepId": "demo:sub:topic:3fa2c1d0e4b5a697:key:2700000390",
 "decision": {"score": 1.2, "confidence": 0.9, "novelty": null, "clip": true, "model": "…"}}
```

- `eventId`: the key event's MA3 id (ETL `keyEvents.id`); the backend's key moment is `km:{eventId}`. `eventSeq`: the seq the decision was made at; the clip shows once a viewer's snapshot reaches it.
- The backend keeps one clip per (topic, moment) and drops clips of a topic it does not know.
- A topic whose kind `clips.always_for` names is clip-on from creation: on a clip moment it is a candidate for, its verdict carries `clip` without the clip `Score` question.

### Key-event clips (`type: MomentClip`)

**Implemented.** Same topic. One message per key event of `clips.key_types` that triggers the shared (bucket) author step, when the `clips` of the last subscription-targets read have `enabled` and `shared` (no follow or decision model needed; `shared` missing reads as off); sent before and apart from that step's narratives, so their grounding never decides it. Re-sent on a step retry; `MessageId` = `id`; application properties `matchId` and `kind: "clip"`.

```json
{"type": "MomentClip", "id": "mclip:demo:2700000390", "matchId": "demo", "buckets": ["home:casual", "neutral:simple"],
 "eventId": 2700000390, "eventSeq": 812, "stepId": "demo:key:2700000390"}
```

- `buckets`: the step's active buckets. The backend adds the moment's clip to each bucket's key-event playlist (`moment_playlist` for that bucket's Insights viewers), bounded to the viewer's snapshot by `eventSeq`, purged and seeded with the match.

**Local stack:** `narrative-live` publishes to the emulator's `narratives` topic. `matchId` is the feed's `{fixture}-{run8}`; any number of matches run at once, each with its own orchestrator.

## Inputs from the user backend

**Implemented.** Read-only, with `ETag`/`If-None-Match`, re-read at most every `BACKEND_CACHE_SECONDS` (5 s) and polled every `TARGETS_POLL_SECONDS` (5 s) for live matches:

| Request | Used for |
| --- | --- |
| `GET /matches/{matchId}/audience-config` | `generation_targets` for this run-scoped matchId (the backend resolves its fixture's audience template): the active buckets and their layer/option descriptions. Empty = write nothing; a newly active bucket gets a `catchUp` narrative |
| `GET /storyline-policy` | `{table, revision, value: {analysis, storylines, repair, claims}}` (ETag): every storyline tunable ([analysis](../docs/components/analysis.md)); unavailable pauses the work |
| `GET /narrative-prompts` | Global active template per role (`minute-summary`, `context-compression`, `match-analyst`, `narrative-author`, `subscription-decision`, `subscription-author`; the list also has the backend's own `subscription-planner`); used only if its placeholders equal the shipped file's |
| `GET /matches/{matchId}/subscription-targets` | Followed topics and the follow tunables (below); poll like the audience targets. Empty `topics` = no follow work |

### Subscription targets

**Implemented in the backend and read by the engine.** Shape (ETag/`If-None-Match`; `revision` grows with every follow, unfollow and follower bucket change; `config_revision` with every `/dev/config/subscriptions` edit):

```json
{"schema_version": 1, "match_id": "riverton-forgeham-1a2b3c4d", "revision": 7, "config_revision": 1,
 "decision": {"instructions": "How far does this update move the followed story?",
              "levels": ["It does not touch the story", "...", "It is a turning point for the story"],
              "trigger_level": 2, "min_confidence": 0.3},
 "novelty": {"enabled": true, "min_probability": 0.5,
             "instructions": "Is this update a new development compared with the last update the viewer got?"},
 "prefilter": {"minute_recaps": true, "key_events": true, "storyline_updates": true},
 "limits": {"min_minutes_between_narratives": 1, "max_topics_per_match": 50,
            "planner_turns_per_minute": 6, "follow_changes_per_minute": 4, "planner_context_turns": 6,
            "pivotal_key_types": ["Goal", "OwnGoal", "RedCard", "PenaltyAwarded", "PenaltyMissed", "VarOverturn"],
            "period_end_wrap_up": true},
 "catch_up": {"reason": "A viewer has just started following this story and has not seen it so far.", "retries": 2},
 "clips": {"enabled": true, "key_types": ["Goal", "OwnGoal", "RedCard", "PenaltyAwarded", "PenaltyMissed", "VarOverturn"], "instructions": "…", "levels": ["…"], "min_level": 3, "min_confidence": 0.5, "timing": {"goal": "goal"}, "max_items": 12, "always_for": [], "shared": true},
 "topics": [{"topic_id": "topic:3fa2c1d0e4b5a697", "created_seq": 812, "followers": 2,
             "buckets": ["away:casual", "home:analytical"],
             "spec": {"kind": "storyline", "storyline_id": "sl:riverton-forgeham-1a2b3c4d:2", "team_id": null,
                      "player_id": null, "focus": "", "label": "Riverton Rovers' grip on midfield"}}]}
```

- **`spec.kind`**: `storyline` (one storyline id from this engine), `team` (contestant id), `player` (player id and its `team_id`) or `theme` (`focus` only, the viewer's words). `focus` narrows any kind; `label` is the first follower's name for it.
- **`buckets`**: the followers' current audience buckets. Frame with that bucket's `generation_targets` entry from `audience-config`; skip a bucket that is not there (disabled).
- **Pipeline:** on each minute recap, key event and storyline update allowed by `prefilter` (and at half and full time), the engine keeps the topics the update involves (prefilter by entities: the team or player in it, a storyline it concerns or moved, any theme; topics created after the update's seq are skipped), renders the `subscription-decision` prompt as the state (inputs as the author's: recaps, recent insights, storylines and trends, current stats, the key event ledger; no viewer text) and asks, in one batched call, one `Score` question per candidate (`decision.instructions` plus the followed story, its `focus` quoted as data in that question only; `levels`; keys are positional per call, never topic ids). With `limits.period_end_wrap_up`, half and full time fire every candidate without a question (a wrap-up). A key event that changes the score (goal, own goal, VAR overturn) is judged with the score before and after it in the update; a team or player follow is asked as everything about that team or player. Otherwise a topic triggers when the score's nearest level ≥ `trigger_level` and `confidence ≥ min_confidence`. Light firing guard: at least `limits.min_minutes_between_narratives` of match time since the topic's last narrative (a key event of `limits.pivotal_key_types`, half or full time bypasses it), and, when `novelty.enabled` and the topic has a last narrative, a `Noul(novelty.instructions)` quoting it must reach `min_probability`. No per-follow budget. Followers may follow anything; there is no breadth limit. The decision is stored once (a restart or backlog never asks again); a (topic, bucket) pair new since the last read gets a "story so far" step whose trigger reason is `catch_up.reason`; the author (`subscription-author`) then writes one narrative per follower bucket. On a key event of `clips.key_types` the same call asks each candidate the clip `Score`; at or above `clips.min_level` with `clips.min_confidence` the topic fires with `decision.clip: true` and a `FollowClip` message goes to the backend, which adds the moment's clip to the topic's playlist; such a key event is never skipped by the gap guard. Model calls take gate priority `decision`, between `analysis` and `author`.
- Decision models live in `narrative_engine/decisions/` (`DecisionModel.decide(state, questions)`; Decision-1 via `SystemOneDecisions`, the constrained `LlmClassifierDecisions` fallback; settings `DECISION_*`).


No fallback: while the backend cannot answer (or a prompt is invalid), authoring waits and `GET /health` returns `503 {"status": "unhealthy", "problems": [...]}`. There is no presence topic.

## Admin: purge

`POST /admin/matches/purge` `{"match_id": …}` or `{"all": true}` per the [purge contract](../../local/contracts/README.md#5-purge). Tombstones (and the `all` cut-off) are written to Cosmos first, so a restart plus late notifications cannot recreate a purged match; then the orchestrator stops and its checkpoint, context blocks, narratives, analyses, storylines, follow decisions and follow narratives are deleted. Response `{"match_ids": [...], "purged": {"checkpoints": n, "contextBlocks": n, "narratives": n, "analyses": n, "storylines": n, "subscriptionDecisions": n, "subscriptionNarratives": n}}`. Internal only; with `ADMIN_TOKEN` set (Azure) it also needs `Authorization: Bearer <token>`.

## Admin: demo seeds (`DEMO_SEEDS=1` only)

**Implemented.** Called by demo control, never by the viewer. Without `DEMO_SEEDS=1` both routes are absent (production release). Same bearer rule as the purge.

| Route | Body | Response |
| --- | --- | --- |
| `POST /admin/matches/export` | `{"match_id"}` | `{"match_id", "schema", "containers": {"checkpoints", "contextBlocks", "narratives", "analyses", "storylines": [...]}}` |
| `POST /admin/matches/restore` | `{"match_id", "max_seq", "schema", "containers"}` (`match_id` is the new run's) | `{"match_id", "restored": {container: n}}`; `409` another schema, a known or purged match, documents of another match, narratives past `max_seq`; `422` malformed; `503` failed (retry) |

Restore clears the checkpoint's follow state; follow decisions and follow narratives belong to viewers and are never seeded. The engine then carries on from the seed at the next notification ([demo](../docs/components/demo.md)).
