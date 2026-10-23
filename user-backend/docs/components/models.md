# Models

> **In short:** strict Pydantic contracts for everything that crosses a boundary: SPADL actions, the canonical event, stream envelopes, the rule DSL over SPADL, question replies, audiences, prompts and config tables. Validated data, never executable code.

| | |
| --- | --- |
| **Code** | [`backend/models/`](../../backend/models/) |
| **Style** | `extra='forbid'` on inputs; bounded strings, lists and numbers |
| **Tests** | `test_filter_engine.py`, `test_spadl_contract.py`, `test_spadl_migrations.py`, `test_goal_contract.py`, `test_structured_contract.py`, `test_audiences.py` |

## 1. Actions, events and stream messages

*In short: custom rules and agents read SPADL actions from ETL; the canonical `Event` only clocks the snapshot.*

| Module | Contract |
| --- | --- |
| `actions.py` | `SpadlAction`: one final SPADL action from ETL GraphQL `spadlActions` ([contracts §3](../../../local/contracts/README.md#3-etl-graphql-dab)). Enums come from the generated [`contracts/spadl-reference.json`](../../backend/contracts/spadl-reference.json). Coordinates are **team-relative** (the acting team attacks towards x = 105; y = 0 is its right touchline); `match_time_seconds` is ETL's broadcast `clockSeconds`, floored. Derived: `distance_metres` (start → end) and `shot_outcome` (`goal`, `saved`, `blocked`, `post`, `off_target`, as ETL's catalogue counts on target) and `save_kind` (keeper_save only: `save` as ETL's `shots_saved`, `wide_touch` from `fromShotOffTarget`, `block` from `defensiveBlock`). `MAX_MATCH_ACTIONS` = 20,000 |
| `events.py` | `Event`: the `event` of MatchEvent v2 ([contracts §2](../../../local/contracts/README.md#2-matchevent-v2)). Used only for the snapshot clock, periods, the viewer/lab ticker and gap recovery. `minute_label` is the one broadcast-minute rule (51:18 → 52′, 45:30 in the first half → 45+1′) |
| `match_stream.py` | `MatchEventV2` (`event.match_id == matchId`, `event.sequence == seq`) and `MatchInfo` (MA1 identity only) |
| `engine_narratives.py` | The engine's Service Bus messages: a narrative, a follow's moment clip (`FollowClip`) or a key event's clip for the shared narratives (`MomentClip`) |

## 2. Rules

*In short: conjunctions of typed SPADL predicates with count or sum, plus bounded composites.*

`rules.py`: a `Rule` is a match id, predicates and an aggregate (`count`, `sum` or `count_present` of `distance_metres`), or a composite (`percentage`, `ratio`, `difference`, `average`) of exactly two aggregate inputs. `calculation_id` is a canonical hash in the `spadl-v1` namespace, so equivalent rules share one calculation. `stat_offers.py` gives pins a stable id: `standard:{statId}` or the rule's calculation id.

| Predicate field | Ops | Values |
| --- | --- | --- |
| `action_type`, `result`, `bodypart`, `start_zone`, `end_zone`, `shot_outcome`, `save_kind` | `eq`, `in` | SPADL enums only |
| `team_id`, `player_id` | `eq`, `in` | Match catalogue ids |
| `period` (1–5), `match_time_seconds` (0–12000) | all | Broadcast minute time |
| `start_x`, `end_x` (0–105), `start_y`, `end_y` (0–68) | all | Team-relative metres |

`coverage=recorded` counts only actions whose body part a provider qualifier named (`bodypart_observed`) and needs a `bodypart` predicate.

**Old → SPADL** ([`020_spadl_rules.py`](../../migrations/020_spadl_rules.py), table `rule_vocabulary_map`):

| Old `event_type` | SPADL |
| --- | --- |
| `pass` | pass family (`pass cross throw_in freekick_crossed freekick_short corner_crossed corner_short goalkick`) |
| `shot` / `goal` / both | shot family (`shot shot_penalty shot_freekick`) + `result fail` / `result success` / no result |
| `corner` | `corner_crossed corner_short` |
| `save` | `keeper_save` (every Opta save, blocks included) |
| `free_kick` | `freekick_crossed freekick_short shot_freekick` |
| `penalty` | `shot_penalty` |
| `offside` | pass family + `result offside` |
| `interception`, `blocked_pass` | `interception` |
| `goal_kick`, `keeper_pickup`, `punch`, `ball_touch` | `goalkick`, `keeper_pick_up`, `keeper_punch`, `bad_touch` |
| `tackle`, `clearance`, `foul`, `throw_in`, `keeper_claim`, `take_on` | same name |
| `touch`, `card`, `aerial`, `ball_recovery`, `kick_off`, `foul_won`, `dispossessed`, `challenge`, `out`, `corner_awarded`, `offside_provoked`, `error`, `period_start`, `period_end` | **unsupported** (no SPADL action) |

| Old `outcome` / `body_part` | SPADL |
| --- | --- |
| `success`, `failure` | `result success`, `result fail` |
| `saved`, `off_target`, `post`, `blocked` | `shot_outcome` of the same name |
| `red`, `yellow`, `second_yellow` | unsupported (cards are outside SPADL) |
| `head`, `left_foot`, `right_foot` | `head`, `foot_left`, `foot_right` |
| `foot` | `foot foot_left foot_right` |
| `other`, `hand` | `other` |

## 3. Questions

*In short: a snapshot is `(matchId, seq)`; replies are validated drafts plus code-computed values.*

`questions.py`: `MatchSnapshot` (`id`, `seq`, clock, period, video seconds), `SnapshotInput` (received events, final SPADL actions with `finalSeq ≤ seq`, teams, players, data reference), `QuestionDraft` (what an agent may return: kind, status, text ≤ 1800, evidence ids ≤ 20, replay items ≤ 36, clarification) and `QuestionReply` (draft + snapshot, offers, evidence, mode, replay, usage). `clarifications.py`: one follow-up question with ≤ 5 options.

## 4. Audiences, prompts, config

*In short: configuration documents validated on every write.*

| Module | Contract |
| --- | --- |
| `audiences.py` | `AudienceConfig`: ≤ 8 layers, each with ≤ 20 options `{id, description, label?}`; ≤ 48 buckets `{id, selections, enabled}`. Every bucket selects one existing option per layer; ids and combinations are unique. `targets()` = the enabled buckets with their layer and option descriptions expanded |
| `viewer_audience.py` | The viewer's choice: `{bucket_id}` of one enabled bucket of the match |
| `prompts.py` | Prompt templates: `{name}` placeholders, fixed per role by the seed, ≤ 20,000 characters |
| `config.py` | One model per `backend_config` row (`CONFIGS`): `presentation`, `replay-timing`, `key-moment-ranks`, `prices`, `stream`, `subscriptions`, `key-moment-feed`, `storyline-policy`, `cross-match`, `follow-offer`, `models` ([routes §6](routes.md#6-config-tables)) |
| `profiles.py` | Demo profiles: `{id, display_name, selections}` |
| `subscriptions.py`, `stat_offers.py` | Follow specs and drafts; pin ids |
