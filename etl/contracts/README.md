# ETL contracts

> **In short:** one Event Hubs stream per match in (MA1, MA3, POS and canonical `MatchEvent` v2), GraphQL (including SPADL actions) and Service Bus notifications out. MA1/MA3 v1 fields are unchanged; the multi-match additions below run in the local stream (`etl-stream`) and in the Stream Analytics query on Azure (MA1, MA3, POS, `MatchEvent` v2, watermark marks), equal by test.

| | |
| --- | --- |
| **Inputs** | Event Hubs `match-events`, partition key `matchId`: `MA1`, `MA3`, `POS` ([schema](match-event.schema.json), [codes](opta-codes.json)) and `MatchEvent` v2 ([local contracts](../../local/contracts/README.md#2-matchevent-v2)) |
| **Outputs** | DAB GraphQL (below and [local contracts](../../local/contracts/README.md#3-etl-graphql-dab)); Service Bus `match-notifications` |
| **Match identity** | `matchId = {fixture}-{run8}`, minted by the feed; never reused |
| **Snapshot identity** | `(matchId, seq)`; `seq` = canonical `MatchEvent` sequence |
| **Admin** | `POST /admin/matches/purge` ([purge contract](../../local/contracts/README.md#5-purge)); with `DEMO_SEEDS=1` only, [seed export and restore](#admin-demo-seeds-demo_seeds-only) |
| **Executable rules** | [reference pipeline](../reference/pipeline.py) |
| **SPADL** | [spadlActions](#output-3-spadl-actions) from MA3 ([schema](spadl-action.schema.json), [rules](../reference/spadl.py)); **implemented, tested and deployed** |
| **Trends** | [Output 4](#output-4-trend-indicators): indicators, spells and momentum at a snapshot ([rules](../reference/trends.py), [definitions](../../local/contracts/README.md#4b-trend-definitions)); **implemented, tested and deployed** |

## Input: Event Hubs `match-events`

*In short: one ordered JSON stream per match, keyed by `matchId`.*

One JSON message per item, partition key `matchId`, so one match is strictly ordered. Every message carries `synthetic: true` for generated data and a wall-clock UTC `timeStamp` (rebased by the feed; Stream Analytics uses it for `TIMESTAMP BY`). `timeMin`/`timeSec` is the Opta match clock (continues through added time; period 2 starts at 45:00). Consumers ignore message kinds they don't use (`feed` absent, or a `type` they don't own).

```text
feed run ─▶ MA1 (~60 s before kickoff)
        ─▶ per canonical event, in seq order:  MatchEvent v2 {seq}  ─▶ its MA3 rows (eventSeq = seq)
        ─▶ POS samples, interleaved by videoSeconds (at equal videoSeconds, POS first)
```

### MA1 additions (match info, sent once)

Existing fields (`matchId description scheduledKickoff timeStamp provenance contestant[]`, lineups) are unchanged. `contestant[].shortName` and `code` (already in the schema) are now always sent. `contestant[].knownNames` (optional) lists other names fans and commentators use ("the Blues"); the narrative engine accepts them in authored text. ETL stores them as `matchTeams.knownNames` (JSON text array, NULL when absent; migration 013), which the user backend's follow chat matches names against.

| Field | Example | Meaning |
| --- | --- | --- |
| `fixture` | `riverton-forgeham` | Feed catalogue id; `[a-z0-9-]{1,55}`. Config (e.g. audience templates) is keyed by it. |
| `sourceMatchId` | `product-demo-match` | The recording's own match id (provenance). Never used as an identity. |
| `runId` | UUID | The feed run; `matchId` = `{fixture}-{first 8 hex of runId}`. |
| `capabilities` | see below | What this feed provides. Stats a capability does not support are served `available: false`, never zero. |
| `branding` | see below | Presentation per contestant id. The frontend uses this, not hard-coded clubs. |

```json
"capabilities": {
  "canonicalEvents": true, "possessionSamples": true, "video": true, "periods": 2,
  "eventTypes": ["touch", "pass", "shot", "goal", "corner", "..."],
  "shotOutcomes": true, "shotsIncludeScoringAttempts": false, "restartEvents": "taken",
  "bodyParts": false, "bodyPartEventTypes": ["pass", "shot", "goal"],
  "bodyPartActionTypes": ["pass", "cross", "throw_in", "freekick_crossed", "freekick_short", "corner_crossed",
                          "corner_short", "goalkick", "shot", "shot_penalty", "shot_freekick"],
  "distanceEventTypes": ["pass", "clearance"], "coordinates": "opta_0_100",
  "clock": "broadcast_with_stoppage", "possessionBasis": "confirmed_native_ownership"
},
"branding": {
  "riverton": {"primaryColour": "#001c68", "secondaryColour": "#0743b7", "crestAssetId": "riverton"},
  "forgeham":  {"primaryColour": "#c7142b", "secondaryColour": "#7b0015", "crestAssetId": "forgeham"}
}
```

- `video: true` means HLS at `/media/hls/{matchId}/live.m3u8`. `periods` is the final period; its `period_end` finishes the match.
- Body parts: `bodyParts: true` covers every event. Otherwise `bodyPartEventTypes` lists the provider's (canonical) event types with complete body parts and `bodyPartActionTypes` the same coverage as [SPADL action types](#output-3-spadl-actions): the pass family when passes are covered, the shot family when shots and goals are. The stat catalogue reads `bodyPartActionTypes`.
- Undeclared means unavailable, never complete: a missing key (or a missing `capabilities`) gives that channel's stats `available: false` and the backend refuses custom rules that need it (body parts, shot outcomes, locations), saying the data is unknown.
- The capability keys are the recording's `capabilities`, camelCased. `crestAssetId` names `frontend/assets/league/clubs/{id}.svg`; unknown or null shows initials.

### MA3 additions

Unchanged v1 fields, including MA3 `seq` (order of MA3 rows: 1, 2, 3… per match in send order). Already sent: `videoSeconds`, `sourceEventId`, `possessionId`. New: **`eventSeq`**, the canonical `MatchEvent` seq this row derives from. Several MA3 rows can share one `eventSeq`. Many canonical events (e.g. `touch`, taken restarts) have no MA3 row.

### POS (new): possession samples

Measured ball ownership, one message per sample, sent only once its video time has played.

```json
{"feed": "POS", "schemaVersion": 1, "matchId": "riverton-forgeham-1a2b3c4d", "synthetic": true,
 "sampleId": 1, "periodId": 1, "videoSeconds": 1.0, "durationSeconds": 0.74,
 "contestantId": "forgeham", "eventSeq": 4, "timeStamp": "2026-10-20T15:00:01.000Z"}
```

| Field | Meaning |
| --- | --- |
| `sampleId` | 1, 2, 3… per match; idempotency key `(matchId, sampleId)`. |
| `videoSeconds` | End of the sample on the match video clock (the recording's `possession_samples[].video_seconds`). |
| `durationSeconds` | Seconds the contestant owned the ball in the sample (`duration_seconds`); unowned ball is excluded. |
| `contestantId` | Owning team (`team_id`). |
| `periodId` | Period at `videoSeconds`. |
| `eventSeq` | Latest canonical seq sent before this sample (informational). |

**Possession at seq s** = per-contestant sum of `durationSeconds` over samples with `videoSeconds ≤ videoSeconds(event s)`, as a percentage of all samples counted (1 dp). The final `period_end` carries the media duration, so the final seq counts every sample. This equals the retired demo ETL's `possession(cursor)`.

## Output 1: GraphQL (Data API builder, anonymous read)

*In short: read-only GraphQL over the ETL tables, views and procedures.*

Local: `http://localhost:5000/graphql` (`devtools local-up`) or `http://localhost:15001/graphql` (shared stack, `./dev up backend`). Azure: internal ingress only (`terraform -chdir=etl/infra output graphql_url`), reachable from apps in the shared Container Apps environment; it scales to zero, so the first request can take ~30 s (the database may also be resuming from auto-pause). All queries support `filter`, `orderBy`, `first`, `after`.

| Query | One row per | Use |
| --- | --- | --- |
| `matches` | match | Team names, `homeContestantId`/`awayContestantId`, full MA1 `payload` (lineups). |
| `rawEvents` | event | History. Typed columns plus full message in `payload` (qualifiers). Indexed `eventSeq` (the MA3 row's canonical seq): a snapshot `(matchId, seq)` reads rows with `eventSeq ≤ seq`. |
| `keyEvents` | key event | Authoritative narrative ledger (see types below). |
| `minuteStats` | contestant, minute, window | Per-minute deltas. Usually prefer `matchStatsAsOfs`. |
| `matchStatsAsOfs` | contestant, match minute | Running totals as of the end of that minute. |
| `matches` (extended), `matchWatermarks`, `statDefinitions`, `canonicalEvents`, `possessionSamples`, `executeStatsAtSeq` | see [local contracts](../../local/contracts/README.md#3-etl-graphql-dab) | Multi-match viewer data and the stat catalogue. Run locally (`etl-stream` + `etl-dab`); on Azure from Stream Analytics. |
| `spadlActions` | action ([below](#output-3-spadl-actions)) | SPADL actions converted from MA3; the stat catalogue counts these. |
| `trendDefinitions`, `executeTrendsAtSeq`, `executeTrendSpellsAtSeq`, `executeTrendMinutesAtSeq` | definition; indicator × team × window; spell; minute × team ([below](#output-4-trend-indicators)) | Trend indicators for the narrative engine's analyst. |

`matchStatsAsOfs` columns: `matchId contestantId position periodId timeMin minuteLabel goals ownGoals passes passesCompleted shots shotsOnTarget corners fouls yellowCards redCards events possessionPct`.

- **As of minute t:** `filter: {matchId: {eq: $m}, periodId: {eq: 2}, timeMin: {eq: 70}}` (one row per team).
- **Current:** `orderBy: {periodId: DESC, timeMin: DESC}, first: 2`.
- `goals` already includes own goals by the opponent and VAR overturns; `ownGoals` counts own goals the team scored against itself.
- `minuteLabel` is broadcast style: `timeMin` 46 in period 1 is `45+2'`. `possessionPct` is share of passes.
- Rows exist only for minutes with at least one event; half time has none.

Example:
```graphql
query ($m: String!) {
  matchStatsAsOfs(filter: {matchId: {eq: $m}}, orderBy: {periodId: DESC, timeMin: DESC}, first: 2) {
    items { position minuteLabel goals shots shotsOnTarget possessionPct redCards }
  }
  keyEvents(filter: {matchId: {eq: $m}}, orderBy: {eventTime: ASC}) {
    items { id keyType detail contestantId playerId periodId timeMin timeSec relatedEventId }
  }
}
```

### Key event types

| keyType | detail | Source | `contestantId` is |
| --- | --- | --- | --- |
| `Goal` | `penalty` or null | type 16, no qualifier 28 | scoring team |
| `OwnGoal` | null | type 16 + qualifier 28 | team that put it in its own net (opponent benefits) |
| `PenaltyAwarded` | `conceded` | type 4, outcome 0, qualifier 9 | team that **conceded** the penalty |
| `PenaltyMissed` | null | type 13/14/15 + qualifier 9 | taking team |
| `RedCard` | `second-yellow` or null | type 17 + qualifier 32/33 | sent-off player's team |
| `VarOverturn` | `goal-overturned`, `own-goal-overturned` | type 900 + qualifier 901 | team of the overturned goal; `relatedEventId` = its `eventId` |

## Output 2: Service Bus topic `match-notifications`

*In short: one topic of minute, key-event and period notifications, at least once.*

JSON body; application property `notificationType` (same value as `messageType`) for subscription filters; `MessageId` set for duplicate detection (delivery is at least once, so consumers should still be idempotent). Every message carries the same keys (`messageType messageId matchId periodId timeMin timeSec eventTime windowEnd id keyType detail typeId contestantId playerId relatedEventId`); keys a type does not use are `null`. Switch on `messageType`.

| messageType | Body fields | MessageId |
| --- | --- | --- |
| `KeyEventDetected` | the `keyEvents` row fields | `{matchId}:key:{id}` |
| `MinuteClosed` | `matchId periodId timeMin windowEnd` | `{matchId}:minute:{periodId}:{timeMin}` |
| `PeriodStarted` / `PeriodEnded` | `matchId periodId eventTime` | `{matchId}:{messageType}:{periodId}` |

- `MinuteClosed` fires when a match minute's window closes (after the late-arrival tolerance). No events, no window: nothing fires during half time.
- `MinuteClosed` and the SQL write for that minute happen together. If `matchStatsAsOfs` has no row for that minute yet, retry briefly.
- Replays can run faster than real time (`--speed 10` gives 6-second minutes), so don't assume 60 seconds per minute.

**Status:** verified against the reference pipeline on Azure. Subscription `narrative-engine`; for now consumers authenticate with the listen-only key (`terraform -chdir=etl/infra output -raw servicebus_listen_connection_string`), to be replaced by Entra roles later. In the shared Docker stack, `local_stream/` sends the same bodies, properties and MessageIds to the Service Bus emulator (subscription `narrative-live`). Offline, `python -m devtools load-local` writes the same message bodies to `etl/.local/notifications.jsonl`. On Azure, messages only flow while the Stream Analytics job is running (the stream schedule starts it when match events arrive and stops it after 30 quiet minutes) and the feed (or a seeder replay) is sending.

## Output 3: SPADL actions

*In short: standard SPADL, converted from MA3 by the ETL, readable per snapshot.*

[SPADL](https://github.com/ML-KULeuven/socceraction) (Soccer Player Action Description Language) is the action contract across the stack: one row per on-the-ball action with a type, result, body part, start and end location. ETL converts MA3 with [reference/spadl.py](../reference/spadl.py), a pure-Python port of socceraction 1.5.3's Opta rules (MIT, [notice](../reference/THIRD-PARTY-NOTICES.txt)); tests compare every recording with socceraction itself, no differences allowed. Atomic-SPADL and VAEP are not used.

```text
MA3 rows (rawEvents) ─▶ SPADL post-processor (spadl/worker.py) ─▶ dbo.spadlActions ─▶ DAB spadlActions
                      reads up to matchWatermarks.seq              writes only final rows, then spadlSeq
```

| | |
| --- | --- |
| **Entity** | `spadlActions` ([schema](spadl-action.schema.json)); key `(matchId, actionId)` |
| **Frame** | Metres, 105 × 68; the home team attacks towards x = 105 in every period (SPADL's convention) |
| **Types** | `pass cross throw_in freekick_crossed freekick_short corner_crossed corner_short take_on foul tackle interception shot shot_penalty shot_freekick keeper_save keeper_claim keeper_punch keeper_pick_up clearance bad_touch dribble goalkick` (`non_action` is never stored) |
| **Results** | `fail success offside owngoal` (`yellow_card red_card` exist in SPADL but Opta cards are separate events) |
| **Body parts** | `foot head other head/other foot_left foot_right`; `bodypartObserved` says a qualifier named it |
| **Extensions** | `seq finalSeq sourceEventId sourceTypeId clockSeconds videoSeconds possessionId bodypartObserved startZone endZone fromShotOffTarget defensiveBlock` |
| **Saves** | SPADL turns every Opta save (type 10) into `keeper_save`. `fromShotOffTarget` (qualifier 190: the keeper touched a shot going wide) and `defensiveBlock` (qualifier 94: an outfield block) mark the ones that are not goalkeeper saves; a real save has both false |
| **Zones** | Relative to the acting team: `own_box defensive_third middle_third final_third opp_box` (thirds at 35/70 m, boxes 16.5 × 40.32 m) |
| **Outside SPADL** | Cards, VAR and penalties awarded (`keyEvents`, MA3 card rows); possession (`possessionSamples`) |

**Live finalisation.** The post-processor stores an action only once nothing later can change it, with `finalSeq` = the canonical seq that settled it: a shot or goal at its own seq; most others at the next one or two actions (a clearance's end is the next action's start, a pass may be deflected, a dribble needs the next action); `period_end` settles the rest of its period. `actionId` counts 0, 1, 2… and never changes. `matchWatermarks.spadlSeq` is the highest seq converted.

**Reading at a snapshot `(matchId, s)`:** use `s ≤ spadlSeq` (and `≤ seq`), then `spadlActions(filter: {matchId: {eq: $m}, finalSeq: {lte: $s}}, orderBy: {actionId: ASC})`. Rows past the watermark do not exist yet. `executeStatsAtSeq` returns `[]` above `spadlSeq` (retry).

```graphql
query ($m: String!, $s: Int!, $after: String) {
  spadlActions(filter: {matchId: {eq: $m}, finalSeq: {lte: $s}}, orderBy: {actionId: ASC}, first: 1000, after: $after) {
    items { actionId periodId timeSeconds teamId playerId typeName resultName bodypartName
            startX startY endX endY startZone endZone seq finalSeq clockSeconds videoSeconds }
    hasNextPage endCursor } }
```

Differences from socceraction, none of which changes any recording: look-ahead stops at a period's first `period_end` (so it finalises the period); a shot is never moved by a following deflection (so it is final at once); input is MA3 in seq order, which the feed sends in clock order (socceraction's sort is then the identity); where socceraction would emit NaN at the end of its input, the location is kept. Test fixture for consumers: [spadl-riverton-forgeham.json](../tests/fixtures/spadl-riverton-forgeham.json).

## Output 4: trend indicators

*In short: who controls the game, per window, as of a snapshot; thresholds and claimability are configuration.*

Three procedures recompute from the rows final at `(matchId, s)` on every call, so a backlog read equals the live one. Like `executeStatsAtSeq`, each returns `[]` for an unknown or purged match or for `s` above `seq` or `spadlSeq` (retry), never a partial set. Formulas: [local contracts §4b](../../local/contracts/README.md#4b-trend-definitions); twin [reference/trends.py](../reference/trends.py); [component page](../docs/components/trends.md).

```text
canonicalEvents (minutes) ┐
possessionSamples         ├─▶ dbo.trendMinuteRows(matchId, s) ─▶ trendMinutesAtSeq   minute × team
spadlActions (final)      │       per minute and team             trendsAtSeq         indicator × team × window
rawEvents (MA3, ≤ s)      ┘   trendDefinitions (thresholds) ─▶    trendSpellsAtSeq    spell
```

| Query | Rows | Order |
| --- | --- | --- |
| `trendDefinitions` | One per trend: `trendId family label unit definition enabled direction notableAt highAt changeAt minuteAt minMinutes minBallSeconds requires meaning evidence displayOrder` (`direction` low: levels at or below the thresholds; `requires`: a spell enabled only alongside that kind) | `displayOrder` |
| `executeTrendsAtSeq(matchId, seq)` | Indicators and composites × team × window (`last5 last15 prev10 half match`, non-empty only), plus one `momentum` row per team (`last5`) | home first, `displayOrder`, window |
| `executeTrendSpellsAtSeq(matchId, seq)` | Territory and pressure spells | start, home first |
| `executeTrendMinutesAtSeq(matchId, seq)` | Per minute and team: the components, `momentum`, `territoryMinute`, `pressureMinute` | minute, home first |

- **Windows** are minutes of the current period: `last5`, `prev10` (the 10 before `last5`), `last15`, `half`; and `match`. `baseline` is `prev10` for `last5`, the match before `last15` for `last15`, and the previous period for `half`; `delta = value − baseline`.
- **Flags** come only from `enabled` definitions and full windows (`last5` 5 minutes, `prev10` 10, `last15` 15, `half` and `match` 5): `level` is `high` (≥ `highAt`) or `notable` (≥ `notableAt`; ≤ for `direction` low); `change` is `rising`/`falling` when `|delta| ≥ changeAt` with at least 10 baseline minutes. `flagged` = `level = high` or a `change`. Disabled trends keep their values (decoration) and never flag; a claim needs `flagged`.
- **One window only:** `territory_fade` in `last15` (null without the 15 minutes before it in the period), `att_half_leading` and `att_half_trailing` in `half` (null with fewer than `minMinutes` minutes in that game state); no baseline.
- **Momentum** is per minute (home perspective, the away row negated); its `trendsAtSeq` row is the value now, `baseline` the minute before `last5`.
- Values are team-relative (`contestantId`); shares carry a +1 prior; rates are per 5 minutes; `def_height` is null without defensive actions.

```graphql
query ($m: String!, $s: Int!) {
  trendDefinitions(filter: {enabled: {eq: true}}, orderBy: {displayOrder: ASC}) {
    items { trendId family label unit notableAt highAt changeAt evidence } }
  executeTrendsAtSeq(matchId: $m, seq: $s) {
    trendId family label meaning unit contestantId window minutes fromLabel toLabel value baseline delta level change flagged enabled }
  executeTrendSpellsAtSeq(matchId: $m, seq: $s) {
    trendId contestantId periodId fromLabel toLabel minutes zoneShare shots boxEntries ongoing enabled }
  executeTrendMinutesAtSeq(matchId: $m, seq: $s) {
    periodId minute minuteLabel contestantId possessionSeconds ballSeconds attHalfShare finalThirdShare ftEntries
    boxEntries shots defHeight fouls cards threat momentum territoryMinute pressureMinute } }
```
```json
{"data": {"executeTrendsAtSeq": [
  {"trendId": "field_tilt", "family": "indicator", "label": "share of final-third play", "unit": "share", "contestantId": "riverton",
   "window": "last15", "minutes": 15, "fromLabel": "78'", "toLabel": "90+2'", "value": 0.8977, "baseline": 0.7177,
   "delta": 0.1799, "level": "high", "change": null, "flagged": true, "enabled": true}, …],
 "executeTrendSpellsAtSeq": [
  {"trendId": "territory_spell", "contestantId": "riverton", "periodId": 2, "fromLabel": "55'", "toLabel": "67'",
   "minutes": 13, "zoneShare": 0.8179, "shots": 3, "boxEntries": 19, "ongoing": false, "enabled": false}, …]}}
```

(Riverton Rovers–Forgeham United at full time, values rounded here.) `executeTrendMinutesAtSeq` also has `attHalfSeconds finalThirdSeconds ftActions boxShots buildPasses pressActions defActions tackles challenges aerials takeOns fastBreaks passes forwardMetres passMetres longPasses`.

## Admin: demo seeds (`DEMO_SEEDS` only)

*In short: export and restore one match, demo build only.*

Demo-only routes on the ETL admin API (bearer token like the purge), present only with `DEMO_SEEDS=1` (local compose and the demo build); a production release has none. Implemented and SQL-tested ([component page](../docs/components/local-stream.md#4-demo-seeds-demo_seeds-only)).

| Route | Body / reply | Refusals |
| --- | --- | --- |
| `GET /admin/matches/export?match_id=` | `{match_id, schema, tables: {table: [rows]}}` | `422` bad id, `503` retry |
| `POST /admin/matches/restore` | `{match_id, max_seq, schema, tables}` → `{match_id, restored: {table: count}}` | `409` other schema, known or tombstoned match, rows of another match or past `max_seq`; `413` over 512 MB |

Demo control is the only caller ([demo control](../../local/docs/components/demo-control.md#2-seeds)): it rewrites the seed to the new run's matchId, restores the ETL alongside the backend, then the engine, then releases the feed run.
