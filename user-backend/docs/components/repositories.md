# Repositories

> **In short:** all SQL lives here, one class per table group. Routes never open connections; services never hold a transaction across model work or an upstream call.

| | |
| --- | --- |
| **Code** | [`backend/repositories/`](../../backend/repositories/) |
| **Driver** | psycopg 3 with `dict_row`, pooled through [`Store`](app.md#2-store) |
| **Tests** | Every API test runs against real Postgres in a throwaway schema |

## 1. Repositories

*In short: what each one owns.*

| Repository | Tables | Notes |
| --- | --- | --- |
| `matches.py` (`MatchRepository`) | `received_matches`, `received_events`, `match_calculations`, `match_gaps`, `calculation_id_map` (020), `stream_checkpoints`, tombstones, purge cut-off | `append` commits a batch of events; `update_results` saves results changed by new SPADL actions; the checkpoint upsert keeps the highest position; `purge` tombstones first, then deletes `MATCH_TABLES` children first |
| `questions.py` (`QuestionRepository`) | `question_conversations`, `question_sessions`, `question_turns`, `question_offers`; reads `demo_profiles` | A new session for (viewer, profile, match) replaces that viewer's token and fails any pending turn; `begin`/`finish`/`fail` lock the session row |
| `audiences.py` (`AudienceRepository`) | `audience_templates`, `audience_catalog` | A fixture without its own template inherits `default`; saving a template rewrites every matching match's copy and bumps its revision only on change; one writer per fixture (advisory lock) |
| `config.py` (`ConfigRepository`) | `backend_config` | Optimistic `revision` per document; a stale revision is `409` |
| `prompts.py` (`PromptRepository`) | `narrative_prompts`, `narrative_prompt_active` | Append-only versions with an optimistic active pointer |
| `engine_narratives.py` (`EngineNarratives`) | `engine_narratives`, `narrative_clips` | Text stored as delivered; `items(snapshot, closed_period)` returns what the snapshot may show; a `MomentClip` adds one row per (bucket, moment), `clips` returns those at or before the snapshot's seq |
| `subscriptions.py` (`SubscriptionRepository`) | `subscription_topics`, `subscriptions`, `subscription_revisions`, `subscription_narratives`, `subscription_clips` | One active follow per viewer (unique index); identical follows share a topic; every change bumps the match's targets revision; narratives and clips of unknown or purged topics are dropped; one clip per (topic, moment), the newest `clips.max_items` per topic at a snapshot |
| `backend/demo/seeds.py` (`SeedRepository`, demo only) | A match's stream rows, catalogue, engine narratives and `narrative_clips` | See [demo](demo.md) |
| Profiles (Accounts DB) | `demo_profiles` + revision row | `GET`/`PUT /dev/profiles` replace the list under an expected revision |

## 2. Purge scope

*In short: match rows go, configuration stays.*

`MatchRepository.MATCH_TABLES` lists every match-scoped table. Profiles, audience templates, prompts and `backend_config` are never touched. Purging an unknown match writes its tombstone and returns zero counts.
