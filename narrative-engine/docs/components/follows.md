# Follows

> **In short:** story follows. The engine reads the topics viewers follow from the user backend, asks Microsoft-Decision-1 once per update whether each involved topic moved, and writes a narrative per fired topic and follower bucket. Decisions are stored and pinned, so a backlog or a restart never asks again.

| | |
| --- | --- |
| **Status** | Implemented and unit-tested (22 Oct). Live smoke against the dev Decision-1 deployment (kickoff to 36', two follows, fake author): 37 decisions, Chelsea's goal fired the Chelsea follow, quiet minutes scored below 1. Moment clips (D3), clip-on topics (D6) and shared key-event clips (D7) built 22 Oct, unit-tested and checked on the local stack (a Spurs follower got Palhinha's second yellow as a clip; D7 clips stored for every bucket; PLAN.md §10.7). Not yet run on Azure |
| **Code** | [`narrative_engine/follows/`](../../narrative_engine/follows/): `topics.py` (source), `pipeline.py` (rules), `steps.py` (steps in the orchestrator); test doubles `devtools/follows.py`, `devtools/fake_decisions.py` |
| **Tests** | `test_follows.py` (source, prefilter, gap, fire rule; the Chelsea–United recording live = backlog, restart, story so far, GraphQL, purge; no viewer text in the shared state; clip `Score` in the same call, clip-on topics, one `FollowClip` per verdict, `MomentClip` without a follow or decision model, a backend before migration 041) |
| **Contract** | [Subscription targets](../../contracts/README.md#subscription-targets), [follow narratives](../../contracts/README.md#follow-narratives-kind-subscription), [follow clips](../../contracts/README.md#follow-clips-type-followclip), [key-event clips](../../contracts/README.md#key-event-clips-type-momentclip) |

## 1. Topics

*In short: `HttpTopicSource` polls `GET /matches/{matchId}/subscription-targets` with the ETag, like the audience targets.*

Each topic has an id, `created_seq`, its followers' buckets and a `spec` (`storyline`, `team`, `player` or `theme`, plus `focus`). The document also carries the tunables: `decision`, `novelty`, `prefilter`, `limits` (including `pivotal_key_types` and `period_end_wrap_up`: half and full time fire every candidate without a question) and `catch_up` (the story-so-far step's trigger reason and `retries`). Every queued step copies the topics and tunables of its time. A (topic, bucket) pair that appears after the first read gets one `catchUp` narrative, "the story so far". If that excerpt is dropped as ungrounded, it is queued again as the next minutes close, at a later horizon, up to `catch_up.retries` times.

**Moment clips** (`clips`, PLAN.md §10.2 D3). On a key event of `clips.key_types` the same batched call also asks each candidate the clip `Score` (`clips.instructions` plus the followed story; `clips.levels`). Decision-1 returns the expected level; when its nearest level is at or above `clips.min_level` with `clips.min_confidence`, the verdict carries `clip: true` and the topic fires. The clip goes to the backend as its own `FollowClip` message ([contract](../../contracts/README.md#follow-clips-type-followclip)), sent before and apart from the topic's narratives, so a narrative dropped as ungrounded never loses the moment's clip. A key event of `clips.key_types` also bypasses the gap guard. No extra call: the clip questions ride in the decision request. A topic whose kind `clips.always_for` names (PLAN.md §10.2 D6) is clip-on from creation: it is not asked the clip `Score`, and every clip moment it is a candidate for clips. With `clips.shared` (D7), the shared key-event step also sends a `MomentClip` for its buckets ([contract](../../contracts/README.md#key-event-clips-type-momentclip); `core/orchestrator._publish_moment_clip`), from the `clips` settings of the last subscription-targets read, kept apart from the follows (`checkpoint.clips`), so it needs no follow and no decision model. A backend without migration 041 serves neither `always_for` nor `shared`: the engine reads both as off and follows keep running, so either service may deploy first.

## 2. Triggers

*In short: a `subscriptionEval` step per update, ordered with the bucket steps.*

| Update | Step ref | Prefilter flag |
| --- | --- | --- |
| A key event | `sub:key:{id}` | `key_events` |
| A summarised minute (none on a period's last minute) | `sub:scheduled:{period-minute}` | `minute_recaps` |
| A scheduled analysis that moved a storyline (replaces that minute's recap) | `sub:analysis:{period-minute}` | `storyline_updates` |
| Half time, full time | `sub:halfTime:1`, `sub:fullTime:2` | always |

Nothing is queued while no topic has a follower.

## 3. Decision

*In short: prefilter, gap, one batched call, fire rule ([`pipeline.py`](../../narrative_engine/follows/pipeline.py)).*

1. **Prefilter by entities.** A topic is a candidate if it existed by the update's seq and the update involves it. A key event involves both teams, its player and every open storyline (a goal or penalty for one side is one against the other); a minute involves the teams and players in its MA3 events; an analysis involves the storylines it opened, moved or resolved and their teams. A theme is always involved. Period ends involve everything; an empty minute involves nothing.
2. **Gap.** A candidate fired less than `min_minutes_between_narratives` of match time ago (same period) is skipped, unless the update is pivotal for it (`pivotal_key_types`, half or full time).
3. **One call.** At half and full time with `limits.period_end_wrap_up`, every candidate fires without a call (its followers get the period's wrap-up). Otherwise the state is the rendered `subscription-decision` prompt (v2), with the author's inputs: statistics, storylines, flagged trends, key event ledger, match context, recent insights and the update. It holds no viewer text. Questions: a `Score` per candidate (`decision.instructions` plus the followed story's subject, and its `focus` quoted as data), and the novelty `Noul` for each candidate with a last narrative, which is quoted. Keys are positional per call (`t1`, `t1n`), never topic ids; `DECISION_MAX_QUESTIONS` splits larger batches.
   **No cross-viewer leakage.** A topic's focus (and its last narrative) appears only in its own questions; the shared state has no labels, focus or topic ids (v1's `{follows}` list is gone). Topics of different viewers may share a request, since each question is answered on its own against the shared match state, and no question carries another topic's text. A test checks that no focus or topic id reaches the state.
4. **Fire rule.** `score ≥ trigger_level`, `confidence ≥ min_confidence`, and P(new) ≥ `min_probability` when novelty was asked. A declined answer is a no.

The decision document (`subdec:{matchId}:{ref}`: candidates, skips, verdicts, fired, model, tokens) is written once to `subscriptionDecisions`; then the fired list is pinned on the step.

## 4. Authoring

*In short: one `subscription-author` call per fired topic and follower bucket, checked like bucket narratives.*

Variables: the bucket author's (bucket framing, statistics, ledger, context, events, storylines with the followed storyline as focus, trends, the bucket's earlier insights), plus `{follow}` and `{story_so_far}` (this pair's earlier narratives). The grounding check and the decision-model claim checks apply, with the policy's rewrites. Narratives go to `subscriptionNarratives`, then to Service Bus `narratives` with `kind: subscription` and `topicId`; `seq` counts per (topic, bucket).
