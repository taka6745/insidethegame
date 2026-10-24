# Services

> **In short:** the application use cases. `MatchRegistry` and `LiveMatch` own each match's received events (the clock) and its custom rules over SPADL actions read from ETL; the filter engine updates every matching rule per action; `ProductService` keeps one projection per match and composes each viewer's view; `QuestionService` answers at a snapshot; the replay services cut clips deterministically; moment playlists, cross-game reach and the follow offer are ordinary services ([§10](#10-clips-cross-game-and-follow-offers)); the demo seed adapter sits outside them ([demo](demo.md)).

| | |
| --- | --- |
| **Code** | [`backend/services/`](../../backend/services/) |
| **Locks** | Per match: `LiveMatch.lock` (events, rules, purge fence), `LiveMatch._sync` (one SPADL read at a time); per-match session locks in `ProductService` and `QuestionService` (takeover) |
| **Tests** | `test_multi_match.py`, `test_filter_engine.py`, `test_filter_properties.py`, `test_composite_metrics.py`, `test_product.py`, `test_questions.py`, `test_replay.py`, `test_replay_clips.py`, `test_time_index.py`, `test_subscriptions.py` |

## 1. Registry, stream and gaps

*In short: one `LiveMatch` per MA1; consecutive seqs only; a gap is recovered or recorded.*

`match_registry.py` creates a `LiveMatch` when an MA1 is accepted, rebuilds every known match from its received events and saved calculations at startup (values are recounted from ETL's SPADL actions on the next capture; delivery versions only move forward) and purges per match or all. `live_match.py` commits consecutive MatchEvents in one transaction per batch; a redelivered seq is ignored (logged if its content differs).

An event past the next expected seq is buffered. A background task checks every second; once the oldest missing seq has waited `stream.gap_timeout_seconds`, it asks ETL GraphQL `canonicalEvents` for `(matchId, seq)`. Found: the event is committed and the buffer drains. No row while ETL's watermark is past seq: the gap is recorded in `match_gaps`, a deleted placeholder `gap-{seq}` keeps seq contiguous (deleted events never count), and the buffer drains. ETL unreachable or not yet at seq: one more timeout, then the same skip. Each new gap starts its own timeout. Once the first missing seq has timed out, the whole run of missing seqs before the first buffered event is filled in that pass (500 per pass), so a stream outage that lost hundreds of events recovers in seconds, not one per timeout. The Event Hubs checkpoint is held while any gap is open, so a restart replays what was buffered. Open gaps show in `/health` and `/dev/pipeline`.

## 2. Live matches and custom rules

*In short: rules are data over SPADL actions; values are kept per finalSeq.*

```text
capture(match) ─ watermark ─▶ s = min(received seq, watermark seq, spadlSeq)
              └ sync_actions(s): DAB spadlActions with actions_seq < finalSeq ≤ s ─▶ engine.ingest ─▶ values[(finalSeq, value)]
```

`LiveMatch.sync_actions` reads only new final actions (they never change), checks `actionId` continuity and persists changed results. `actions_at(seq)` is the prefix a snapshot reads, so nothing past `spadlSeq` is reachable. `register` validates a rule against the match's capabilities (body parts, shot outcomes, locations) and attribution (a player rule with unattributed matching actions is unavailable, not zero), calculates it over the actions read so far, replays its value history, persists it and adds it to the shared engine. Equivalent rules share one `calculation_id`. `FILTER_MAX_CALCULATIONS` caps distinct calculations per match (default 10,000, 1–1,000,000). `value_at(id, seq)` gives custom cards the same snapshot as ETL stats. A tracked rule with no SPADL equivalent shows as an unavailable card with its reason.

## 3. Filter engine

*In short: a general index over the rule language; each final action is counted once.*

```text
Action → match + categorical keys → predicate families → clock windows → changed totals
```

A family groups rules with identical non-clock predicates and aggregation. Three invariants (`filter_engine.py`, `time_index.py`):

1. **Categorical lookup never discards a possible match.** Equality/membership conditions on `action_type`, `team_id`, `player_id`, `bodypart`, `period`, `result` form compound keys (≤ 64 per family); the rest (zones, shot outcome, x/y) are checked afterwards. An action probes 64 masks.
2. **The clock lookup returns each matching rule once.** Integer seconds `[0, 12000]`; intervals become segment-tree nodes; a point visits its leaf-to-root path.
3. **Actions are final.** One per `(match_id, action_id)`; a duplicate does nothing; conflicting content raises before changing state.

Costs: a new action is `O(D·2^D + F·(log U + P) + C + K log K)` (families `F`, predicates `P ≤ 16`, clock candidates `C`, changed results `K`). Differential tests (`test_filter_properties.py`) check every clock value against an independent interpreter. `distance_metres` (start → end) sums use 28-digit `Decimal`.

## 4. Composite metrics

*In short: two aggregate inputs, one formula, computed in code.*

| Operation | Meaning |
| --- | --- |
| Percentage | `100 × subset / population`; compatible units; the subset must provably keep every population restriction |
| Ratio, difference | `left / right`, `left − right`; compatible units |
| Average | Distance sum / number of matching actions |

Inputs cannot be formulas; zero denominators give `null` (unavailable, still trackable). Each action applies leaf deltas first, then recomputes dependent formulas once; only changed public values advance versions. Not supported: rolling windows, sequences, joins, averages of percentages.

## 5. Replays

*In short: the replay agent picks evidence; `replay_clips.py` picks seconds.*

`replay.py` gives the replay agent bounded tools over one snapshot's SPADL actions and MA3 cards (`find_events` with SPADL filters, `find_cards`, sequences with a recorded `description`, recent minutes, key moments, recaps) and checks captions (an unsaved shot is never called saved). Evidence ids are `a{actionId}` and `card:{id}`; clip timing keys are SPADL types plus `goal` and `card`. `replay_clips.py` cuts each item from the `replay-timing` config (seconds before/after per type, lead-in `short`/`normal`/`long` multipliers, `move` = from the team's last possession gain), clamps to the period and the published playlist's end, merges overlaps and pages (`max_clips` per page, `max_items` per answer). `replay_page` re-cuts a saved replay without a model call.

How long a clip runs: the agent only picks the evidence and a lead-in; code picks the seconds.

| Clip | Length |
| --- | --- |
| Shot, save, card, other action | `timing[type]` before and after (a shot 6 s + 3 s), times the lead-in (`short` 0.5×, `long` 2×) |
| Goal | 10 s before, 5 s after (the reaction) |
| `move` lead-in | from the attacking team's last possession gain, capped at `max_move_seconds` (25 s): a goal after a long build-up runs much longer than one from a rebound |
| Own goal | as a goal; its `move` starts at the attack before the defender's touch, which is often a one-touch possession of its own; its caption always comes from evidence (who scored it, which side it counts for) |
| Any event clip | at least `min_clip_seconds` (8 s), widened backwards, so a quick action with a short lead-in still shows enough to follow. The period start, the viewer's position and the published footage still cut it |
| Key moment | its authored window; a goal moment ends 5 s after the goal |

So clips differ mainly by lead-in: `move` follows the whole attack, the others a fixed window.

## 6. Projections

*In short: one shared snapshot per match; per-viewer composition never queries upstreams.*

`product.py` refreshes a match's projection on every committed change: ETL stats at the snapshot, the score from MA3 goals and VAR decisions, the newest 30 received events (ticker), engine narratives the snapshot may show and custom values at that seq. Unavailable stats carry `unavailable_reason` (ETL's definition, e.g. a retired kind). Each viewer's view: up to `card_slots` cards = pinned stats plus `presentation` defaults (fallbacks when a default is unavailable; excluded stats never shown; pins displace the lowest-priority default, never a protected kind; a default card carries `sides`, its kind's value for home and away, so one slot shows both teams), and the narratives addressed to the viewer's bucket (while following: only the followed topic's narratives for that bucket, [§9](#9-story-follows)), plus the pivotal key moments at the snapshot (`key_moments.py`, `key-moment-feed` config) for everyone. Engine narratives carry no stat recommendations today, so defaults come from config. `live_viewers.py` keeps one bounded queue per socket; a full queue closes it (`1013`) so the client reconnects to a fresh snapshot.

Sessions: one per (viewer, profile, match), where a viewer is one browser. A viewer's new session takes over its previous one for that profile and match (its socket closes `4001`); another browser on the same profile gets its own session and conversation. The viewer may change bucket at any time. Session locks are per match, so one match's takeovers and pins never wait on another's.

## 7. Questions

*In short: model work outside locks; values from code.*

`questions.py` admits at most `QUESTION_MAX_ACTIVE` questions per process (fail fast `503`), captures the snapshot at `min(latest, viewer seq)`, builds bounded context and tools (`question_tools.py`: `actions` search, `cards`, `lookup` of SPADL terms; rankings and one-off values over the snapshot's actions), runs the agent with `QUESTION_TIMEOUT_SECONDS`, resolves the declared source (`question_answers.py`), rejects unverified evidence, and commits under the match guard so a purge cannot interleave. A failure is saved as a receipted refusal.

## 8. Configuration services

*In short: revision-checked documents with a short cache.*

`config.py` re-checks revisions at most every 2 s so edits reach every process. `audiences.py` serves each match's catalogue with an ETag. `prompts.py` serves active prompts and edits versions.

## 9. Story follows

*In short: one follow per viewer; the planner drafts, code resolves ids; everything bounded to the viewer's snapshot.*

`subscriptions.py` validates a follow's ids against the teams, players and storylines at the viewer's `seq` (storylines opened later are unknown, resolved ones refused), stores it under the match guard and republishes the viewer's snapshot. Suggestions are by rule: open storylines by salience, players in the key moments, then teams. The follow chat (`subscription_planner.py`, prompt role `subscription-planner`) reuses the question turn tables (`channel = 'follow'`); names are resolved to ids by rarity-weighted word overlap (`min_name_match`), and a proposal is never a follow until the viewer confirms. `targets` builds the engine's `subscription-targets` document (topics with their followers' buckets, plus the `subscriptions` tunables) with an ETag. Limits come from the `subscriptions` config row ([contracts §8b](../../../local/contracts/README.md#8b-story-follows)).

## 10. Clips, cross-game and follow offers

*In short: ordinary services; nothing branches on a demo.*

| File | Does | Status |
| --- | --- | --- |
| `follow_clips.py` | `moment_playlists`: a followed topic's clips (`subscription_clips`, from the engine's `FollowClip`) and a bucket's key-event clips (`narrative_clips`, from `MomentClip`) cut with `replay-timing` on the match's own stream, chronological, bounded to the viewer's snapshot. Each clip carries its moments' `CARD_FIELDS` (minute, label, team, player, score after) for the preview card. Served as `follow_playlist` and `moment_playlist` | Implemented, tested |
| `cross_match.py` | `CrossMatch.named` finds another live match a viewer's words name (rarity-weighted, best fit wins), `.other` gets one by id, `.listing` gives the agents every live match (teams, minute); `header` marks content (teams and branding, never the score). Each match is read at its own position (config `cross-match`) | Implemented, tested |
| `questions.py` `_follow_offer` | One yes/no per non-statistic answer (`adapters/decision.py`: Microsoft-Decision-1, else the question model); `follow_offer` when it clears `follow-offer.min_probability`; paced and time-boxed, never blocks the answer | Implemented, tested |

Every replay also carries `playback` (`replay-timing.playback`) for the viewer's sting transitions (the league's CSS sting, `builtin:league`) and slow motion.
