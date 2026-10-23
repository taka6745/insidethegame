# Routes

> **In short:** HTTP translation only. Viewer routes live under `/product/matches/{matchId}`; the engine reads `GET /matches/{matchId}/audience-config`, `GET /narrative-prompts`, `GET /storyline-policy` and `GET /model-roles`; developer routes (`/dev`, `/lab`) are mounted only when their flags are set. Every developer write is revision-checked (ETag or `expected_revision`, `409` on conflict).

| | |
| --- | --- |
| **Code** | [`backend/routes/`](../../backend/routes/) |
| **Explorer** | [localhost:18000/docs](http://localhost:18000/docs) |
| **Flags** | `ENABLE_DEV_FEED=1` mounts `/dev/*`; `ENABLE_FILTER_LAB=1` mounts `/lab/*` (both local only, unauthenticated) |
| **Errors** | `{"code", "detail"}` with the status of the `RuleError` |
| **Tests** | `test_multi_match.py`, `test_product.py`, `test_product_audiences.py`, `test_audiences.py`, `test_prompts.py`, `test_questions.py`, `test_viewer_playhead.py`, `test_dev_editors.py`, `test_stream_gaps.py` |

## 1. Viewer API

*In short: a session per (viewer, profile, match); one WebSocket per session.*

`M` = `/product/matches/{matchId}`. The frontend's `/viewer-api/` prefix maps to `/product/`.

| Route | Use |
| --- | --- |
| `GET /product/matches` | Known matches with ETL status, seq, clock, teams (score, branding) and HLS URL: live, then scheduled by kickoff, then finished |
| `GET /product/profiles` | Demo profiles |
| `GET /product/prices` | Answer prices `{input, output}` (US$ per million tokens) with an ETag; receipts estimate cost from these, never from a provider |
| `POST M/sessions` `{profile_id, viewer_id}` | New session for this browser's `viewer_id`; takes over (closes) that viewer's previous socket for the profile and match, never another viewer's. Before the match's MA1: `404 match_not_started`; purged: `404 match_not_found` |
| `GET M/sessions/{token}` | Session, chat turns, offers and the current snapshot |
| `PUT M/sessions/{token}/audience` `{bucket_id}` | Choose one of the match's enabled buckets; `422 audience_unavailable` otherwise |
| `POST M/sessions/{token}/messages` `{prompt, request_id, seq?}` | Ask; `seq` is the snapshot the viewer is showing, and the answer is computed at `min(latest, seq)` |
| `GET M/sessions/{token}/turns/{turn}/replay/{page}` | Another page of a saved replay; no model call |
| `POST M/sessions/{token}/offers/{offer}/track` | Pin an offered stat; `409 cards_full` past the card slots |
| `DELETE M/sessions/{token}/pins/{calculation}` | Unpin |
| `WS M/sessions/{token}/live` | Snapshots, then updates and 20 s heartbeats |
| `GET/POST M/sessions/{token}/follows`, `DELETE …/follows/{id}` | Story follows: list, follow (one per viewer, `409 follow_limit`; may target another live match), unfollow ([contracts §8b](../../../local/contracts/README.md#8b-story-follows)) |
| `GET M/sessions/{token}/follow/suggestions`, `POST …/follow/messages` | Rule-based follow suggestions; the follow chat (planner proposes, the viewer confirms) |
| `GET /matches/{id}/subscription-targets` | Engine only: followed topics, their buckets and the follow tunables (ETag) |

A snapshot carries `version`, `projection_epoch`, `match` (status, scheduled_kickoff, seq, clock, teams, media), `events` (the latest received canonical events: the ticker), `cards` (an unavailable card carries `unavailable_reason`), `narratives` (the viewer's bucket only), `profile`, `audience` `{bucket_id, selections}` and `audience_buckets` `[{id, label}]` (the match's enabled buckets, labels resolved from option labels with `{home}`/`{away}` replaced by team names). A token belongs to one match: under another match it is `404`. WebSocket close codes: `4404` match unknown or purged, `4001` session replaced or rejected, `1013` overloaded or unavailable.

## 2. Lab chat

*In short: the viewer's question use cases without the projection.*

`/lab/chat/profiles`, `/lab/matches/{id}/chat/sessions`, `…/chat/{token}`, `…/{token}/messages`, `…/{token}/turns/{turn}/replay/{page}`, `…/{token}/offers/{offer}/track`. Same bodies as §1.

## 3. Audience configuration

*In short: the backend stores definitions; the engine writes for the enabled buckets.*

```text
/dev/ audience editor → audience_templates (per fixture) → audience_catalog (per match)
                                                                  ↓
Narrative engine ← GET /matches/{matchId}/audience-config (ETag, 304) ← generation_targets
```

`GET /matches/{matchId}/audience-config` (read-only, always mounted) returns one consistent revision:

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `match_id`, `revision` | The match and its catalogue revision |
| `layers` | `[{id, description, options: [{id, description, label, team}]}]` |
| `buckets` | `[{id, selections: {layer: option}, enabled}]`; layers are team, style and length (Standard, Brief; Brief buckets ship disabled) |
| `generation_targets` | The enabled buckets only: `[{bucket_id, selections, layers: [{id, description, option: {id, description, label?, team?}}]}]` (unset fields omitted) |

Generation is driven only by this configuration; viewers never enable or disable a bucket. The engine passes each target's layer and option descriptions to its author as data (`narrative-engine/narrative_engine/audience/targets.py`). Empty `generation_targets` means write nothing. Keep the `ETag` and send `If-None-Match`; `304` means reuse. On an error keep the last valid revision; never treat an error as "generate everything". An unknown or purged match is `404`.

Each match gets a copy of its fixture's template (`default` when the fixture has none) in `audience_catalog`; a template save rewrites every matching match's copy and bumps its revision. Option `label` is the short viewer-facing name (`{home}`/`{away}` become team names); `description` is model-facing; optional `team` (`home`/`away`) says which side the option backs. The engine's "supports" line uses `team`, else a label naming only `{home}` or `{away}`; layer ids carry no meaning.

Developer routes (`ENABLE_DEV_FEED=1`):

| Route | Use |
| --- | --- |
| `GET /dev/audience-templates` | `{templates: [{fixture, revision}], matches: [{match_id, fixture, revision, enabled}]}`: every template, and each match catalogue's enabled bucket ids |
| `GET /dev/fixtures/{fixture}/audience-config` | `{fixture, inherited, revision, config}`; `inherited` until the fixture saves its own |
| `PUT /dev/fixtures/{fixture}/audience-config` `{expected_revision, config}` | Replace layers, options, buckets and `enabled` flags; stale revision `409`; unknown option, missing layer selection, duplicate id or combination `422` |

Bounds: 8 layers, 20 options per layer, 48 buckets. Buckets are explicit combinations (the `/dev/` editor generates them from the options). An option with `in_label: false` (Standard length) is left out of the viewer's bucket name.

## 4. Narrative prompts

*In short: the backend stores prompt versions; the engine reads and fills them.*

`GET /storyline-policy` → `{table, revision, value}` with an ETag: the `storyline-policy` config row (analysis limits and caps, storyline lifecycle and salience, repair turns), validated by `models/config.py` `StorylinePolicy` and edited under `/dev/config/storyline-policy`.

`GET /narrative-prompts` → `{revision, prompts: [{role, version, template, placeholders}]}` (active versions only) with an ETag; `revision` grows on every save or activation. Roles: `minute-summary`, `context-compression`, `match-analyst`, `narrative-author`, `subscription-decision`, `subscription-author`, `subscription-planner`, seeded from the engine's shipped files ([migrations](migrations.md#2-prompt-seeds)). Fill `{name}` placeholders only. The engine pins each narrative step to the version it started with and ignores a template whose placeholders differ from its shipped file.

| Route (`ENABLE_DEV_FEED=1`) | Result |
| --- | --- |
| `GET /dev/narrative-prompts` | Per role: active version, placeholders, last 50 versions |
| `PUT /dev/narrative-prompts/{role}` `{template, expected_version}` | New active version; `409` if `expected_version` is not active; `422` if placeholders differ from the seed's or the template is empty or over 20,000 characters |
| `POST /dev/narrative-prompts/{role}/versions/{version}/activate` | Roll back or forward; `404` for an unknown version |

## 5. Filter lab

*In short: a developer page per live match for custom rules.*

| Route (`ENABLE_FILTER_LAB=1`) | Use |
| --- | --- |
| `GET /lab/matches/{id}/state` | Latest 100 received events, every custom calculation, index metrics |
| `GET /lab/matches/{id}/events/{seq}` | One received canonical event; `404` past what was received |
| `POST /lab/matches/{id}/calculations` `{rule, label}` | Register a SPADL rule ([models §2](models.md#2-rules)); it backfills from the SPADL actions read so far |
| `POST /lab/matches/{id}/plan` `{prompt, conversation_id?}` | Model-planned rule or a clarification; `503` without a model |

Unsupported categories, body parts or distances are refused with the missing data named, from the match's MA1 capabilities. Plan conversations are process-local, expire after 15 minutes and allow three exchanges. Page: [localhost:18020/lab/](http://localhost:18020/lab/).

## 6. Config tables

*In short: tunables in `backend_config`, one validated JSON document each.*

`GET /dev/config/{table}` → `{table, revision, value}` with an ETag (`304` on `If-None-Match`). `PUT /dev/config/{table}` `{value, expected_revision}` or `{value}` with `If-Match`; stale `409`, missing revision `428`, invalid `422`. Edits reach every process within 2 s.

| Table | Holds |
| --- | --- |
| `presentation` | Card slots, default and fallback stats (`{team}` or `all`), excluded stats, protected kinds |
| `replay-timing` | Seconds before/after per SPADL action type (plus `goal` and `card`), lead-in multipliers, clip and page limits; `playback` (sting transitions, slow motion; served with every replay) |
| `key-moment-ranks` | Rank of goal, dismissal, penalty and card |
| `prices` | `{input, output}` US$ per million tokens for answer receipts (public read: `GET /product/prices`) |
| `stream` | `{gap_timeout_seconds}`: how long a seq gap waits before recovery |
| `subscriptions` | Story follows: decision, novelty, prefilter, catch-up, limits, suggestions, `min_name_match`, `clips` (clip question, `key_types`, `always_for`, `shared`) (served to the engine in each match's `subscription-targets`) |
| `key-moment-feed` | Pivotal key-moment kinds every feed shows and their labels |
| `storyline-policy` | Storyline lifecycle, salience and focus rotation (engine read: `GET /storyline-policy`) |
| `cross-match` | Questions, pins and follows about the other live matches: `enabled`, `min_name_coverage`, `suggest_teams` (local/contracts/README.md §8c) |
| `follow-offer` | The "Follow this story?" decision on answers: question, `true`/`false` meanings, `min_probability`, `max_per_minute`, `timeout_seconds` |
| `models` | Model per role: `deployments` offered, `engine` (summary, compression, analyst, author) and `backend` (questions, follow_planner, replay), each `{deployment, effort}`; an empty deployment keeps the service's own setting. The backend applies its roles within seconds; the engine reads `GET /model-roles` (ETag) |

## 7. Demo profiles

*In short: the Accounts database's demo accounts, editable in `/dev/`.*

`GET /dev/profiles` → `{revision, profiles: [{id, display_name, selections: {layer: option}}]}` with an ETag. `PUT /dev/profiles` `{expected_revision, profiles}` replaces the list; stale `409`, invalid `422` (including a selection whose layer or option is not in the default template). Layer ids are data, so renamed layers need no schema change (accounts migration 003 moved the old `team`/`fan_style` columns into `selections`). A profile's selections only choose the viewer's default: the first enabled bucket sharing the most of them. A snapshot's `profile` is `{id, display_name, selections, team}`, where `team` is the contestant the selected options back (an option's `team`, else a `{home}`/`{away}` label), else `neutral`. A session whose profile was removed gets `409 profile_not_found` until the viewer starts a new one.

## 8. Admin, health and pipeline

*In short: internal routes.*

| Route | Use |
| --- | --- |
| `POST /admin/matches/purge` `{match_id}` or `{all: true}` | Tombstone, then delete this service's match rows ([contracts §5](../../../local/contracts/README.md#5-purge)); internal; for `/dev/` via nginx `/purge-api/backend` (basic auth) |
| `POST /admin/matches/export` `{match_id}`, `POST /admin/matches/restore` `{match_id, max_seq, schema, tables}` | **Demo only** (`DEMO_SEEDS=1`; absent otherwise): seed export and restore for demo control ([demo](demo.md)) |
| `GET /health`, `GET /ready` | `200` when a model is configured and the database answers, else `503`; includes the match count and open `gaps` |
| `GET /dev/pipeline` | This service (status `degraded` while a gap is open) plus upstream `/health` probes; `gaps` lists open gaps and the latest 50 filled ones (`recovered`/`skipped`) |
