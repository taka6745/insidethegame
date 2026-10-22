# Migrations

> **In short:** versioned migrations applied once each, in name order, by `Store.initialize()` under an advisory lock. `migrations/*.sql` and data migrations `migrations/NNN_*.py` (a `migrate(conn)` run in the same transaction) build the Match App schema; `migrations/accounts/*.sql` the Accounts database; `migrations/prompts/` holds the prompt seeds.

| | |
| --- | --- |
| **Code** | [`migrations/`](../../migrations/) |
| **Ledger** | `schema_migrations(version, applied_at)` per database |
| **Tests** | `test_migrations.py`, `test_spadl_migrations.py`, plus every test creating a fresh schema |

## 1. Files

*In short: what each file does.*

| File | Effect |
| --- | --- |
| `011_narrative_prompts.sql` | `narrative_prompts`, `narrative_prompt_active`; seeds version 1 of each role |
| `014_multi_match.sql` | Multi-match tables: tombstones, purge cut-off, received matches and events, calculations, checkpoints, chat, engine narratives; drops the single-run tables |
| `015_audience_templates.sql` | `audience_templates` (with the twelve-bucket `default`) and `audience_catalog` |
| `016_config.sql` | `backend_config` with `presentation`, `replay-timing`, `key-moment-ranks` |
| `017_drop_orphaned_narrative_tables.sql` | Drops the retired backend framing tables |
| `018_config_only_audiences.sql` | Audiences become config-only: existing pins become `enabled` flags, `pinned_buckets` and `viewer_counts` are dropped, an unedited `default` template enables `home:analytical`, `away:casual`, `neutral:simple` (the demo profiles' buckets) and options gain viewer labels; match catalogues are re-copied |
| `019_prices_and_stream_gaps.sql` | `prices` and `stream` config rows; `match_gaps` (filled seqs) |
| `020_spadl_rules.py` | Custom rules move to SPADL: seeds `rule_vocabulary_map` ([old → SPADL](models.md#2-rules)); rewrites each saved calculation and its tracked offers to the SPADL rule and new `calculation_id`, recording `calculation_id_map(match_id, old_id, new_id, reason)` so tracked cards follow; a rule with no SPADL equivalent (touches, cards, …) is removed and its offers get `unsupported` (shown as an unavailable tracked card); untracked old offers can no longer be tracked. Values are recounted from ETL on the next load |
| `021_spadl_prompts.py` | Adds the SPADL `narrative-author` and `minute-summary` seeds as each role's next version; activates them only where the role still runs an unedited seed |
| `022_spadl_replay_timing.py` | Renames `replay-timing` keys to SPADL types (`save` → `keeper_save`, `corner` → `corner_crossed`/`corner_short`, …); keeps edited seconds; drops keys with no action (offside, foul_won, corner_awarded) |
| `023_storyline_prompts.py` | Storylines: adds the `match-analyst` role (version 1) and makes `narrative-author` v5 active over any v4 or edit of it, since v5 adds `{storylines}` and `{match_trends}`; an existing edit of v5 stays; a fresh store is left to the startup seed |
| `024_subscriptions.py` | Story follows: `subscription_topics`, `subscriptions` (one active per viewer, unique index), `subscription_revisions`, `subscription_narratives`; `question_turns.channel` (`questions`/`follow`) and `created_at`; config rows `subscriptions` and `key-moment-feed`; adds the roles `subscription-planner`, `subscription-decision`, `subscription-author` (version 1) to an existing store. All match-scoped and purged ([contracts §8b](../../../local/contracts.md#8b-story-follows)) |
| `025_grounded_prompts.py` | Grounding: adds `match-analyst` v2 and `narrative-author` v6 (placeholders unchanged) as each role's next version; activates them only where the role still runs an unedited seed |
| `026_storyline_policy.py` | Config row `storyline-policy` from `seeds/storyline-policy.json` (the engine's storyline tunables; the engine ships a byte copy for its tests); an edited row is kept |
| `027_follow_triggers.py` | Adds `subscriptions.limits.pivotal_key_types` (key events that bypass a topic's minimum gap) and `storyline-policy.claims` (the engine's decision-model claim checks, from the seed) to existing rows; edited keys are kept |
| `028_key_moment_labels.py` | `key-moment-feed` labels in the developer's wording (`Goal · {team} · {scorer}`, `Red card · {player}`, `Half time · {score}`) plus the `score` template; labels still equal to the 024 seed are rewritten, edited ones kept |
| `029_policy_prompts.py` | Adds `storyline-policy.claims.result` (the result question that replaced the engine's phrase list), `subscriptions.limits.planner_context_turns` and `subscriptions.catch_up` where missing (edits kept); adds `match-analyst` v3 (limits as policy placeholders) and `subscription-decision` v2 (no `{follows}`), active even over an edit since their placeholders change |
| `030_grounded_patterns.py` | Adds `subscriptions.limits.period_end_wrap_up`, each claim's `analyst` flag and the `comparison` claim to existing rows (edits kept), and analyst prompt v4 where the seed is unedited |
| `031_policy_limits.py` | Adds `storyline-policy.storylines` `beats_shown`, `resolved_shown_minutes` and `author_match_indicators`, and `subscriptions.max_candidates`, to existing rows (edits kept) |
| `032_follow_retries.py` | Adds `subscriptions.catch_up.retries`, and turns on the intent claim's `analyst` flag where that claim is unedited |
| `033_comparison_claim.py` | Rewords the `comparison` claim's question, support and repair (support may come from a storyline beat or recap, read with what each indicator measures) where the claim is still as `030` seeded it |
| `034_result_claim.py` | Rewords the `result` claim so a half-time score or the current standing is not how the match ended, where the claim is still as `030` seeded it |
| `035_author_trim.py` | Adds `storyline-policy.repair.author_trim` (true) where missing: an excerpt keeps its supported sentences |
| `036_score_claim_reopen.py` | Adds `storyline-policy.claims.score` (a sentence's score, or what a goal did to it, checked against the ledger) and `storylines.reopen_within` (15 minutes: a resolved storyline of the same label reopens) where missing |
| `037_replay_playback.py` | Adds `replay-timing.playback` where missing (edits kept): clip transitions (hold, sting asset and its start, cut, fades) and slow motion around marked events, each with `enabled`; served with every replay as `playback` |
| `038_follow_clips.py` | Adds `subscription_clips` (a followed topic's moment clips, purged with the match) and `subscriptions.clips` (the clip question, clippable kinds and their replay-timing keys) where missing (edits kept) |
| `039_follow_clip_step.py` | Renames `subscription_clips.narrative_id` to `step_id`: clips arrive as the engine's `FollowClip` message, not on a follow narrative |
| `040_cross_match.py` | Config rows `cross-match` and `follow-offer` (edits kept); `subscriptions.bucket_id`, the bucket a follow of another match is written for (PLAN.md §10.2 D5, D5b) |
| `041_capture_clips.py` | `narrative_clips` (key-event clips on the shared narratives, per bucket and moment; purged and seeded with the match); adds `subscriptions.clips.always_for` (clip-on topic kinds) and `.shared` where missing, keeping edits (PLAN.md §10.2 D6–D7) |
| `042_shorter_author_planner_options.py` | `narrative-author` one or two short sentences (active over the unedited seed only); `subscription-planner` v2 with `{live_matches}` and up to four clarification `options` resolved by code |
| `043_narrative_clips_match.sql` | `narrative_clips` rows belong to a received match (cascade on purge); orphans removed |
| `044_clip_relevance.py` | the clip decision asks how relevant a moment is to the followed story (`clips.instructions` and `levels`), only where both are still 038's wording |
| `045_viewer_sessions.sql` | each browser is its own viewer: conversations and sessions keyed by (`viewer_id`, profile, match); another browser on the same profile never takes a session over (PLAN.md §12 M1) |
| `046_clip_lengths.py` | `replay-timing.min_clip_seconds` 8 s, and a goal keeps 5 s after (was 2 s), each only where unedited |
| `047_model_roles_length_layer.py` | `backend_config.models` (model per role, live; empty deployments keep each service's own setting) and an audience `length` layer (Standard, Brief) in every template and catalogue: existing buckets keep their ids and select Standard, Brief twins are added disabled |
| `accounts/001_demo_profiles.sql` | `demo_profiles` with three demo accounts |
| `accounts/002_profile_editor.sql` | Profile revision row for the `/dev/` editor; drops the hard-coded team/style CHECK constraints |
| `accounts/003_profile_selections.sql` | `team`/`fan_style` columns become a `selections` map (layer id → option id) |
| `accounts/004_fixture_neutral_profile_names.sql` | Unedited seeded names by side (`Home analyst`, `Away fan`), since profiles serve every fixture |

Configuration rows are inserted `ON CONFLICT DO NOTHING`, so edits made in `/dev/` survive restarts.

## 2. Prompt seeds

*In short: byte-for-byte copies of the engine's shipped prompts.*

`migrations/prompts/` holds `minute-summary.txt` (engine v2), `context-compression.txt` (v1), `match-analyst.txt` (v3), `narrative-author.txt` (v6), `subscription-decision.txt` (v2), plus `narrative-author.v4.txt` (for `021`), `match-analyst.v1.txt` and `narrative-author.v5.txt` (for `023`), `subscription-decision.v1.txt` (for `024`), `match-analyst.v2.txt` (for `025`); v2 and v4 add a short SPADL glossary, v5 the storylines, analyst v2 confidence levels and the side-by-side trend table, author v6 trend units without an example excerpt. Copied from the narrative engine so the backend never reads another service's folder at runtime ([seed notes](../../migrations/prompts/README.md)). A fresh store gets them as version 1; `021`, `023`, `025` and `029` add them to an existing one. Each seed's `{name}` tokens fix that role's placeholder set (unchanged by SPADL; v5 adds two, so `023` activates it; analyst v3 and subscription-decision v2 change theirs, so `029` activates them).
