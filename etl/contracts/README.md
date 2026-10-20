# ETL contracts

What other services can rely on. Inputs: [match-event.schema.json](match-event.schema.json), codes in [opta-codes.json](opta-codes.json). The [reference pipeline](../reference/pipeline.py) is the executable version of the rules below.

## Input: Event Hubs `match-events`

One JSON message per Opta event, partition key `matchId`. An `MA1` match-info message (teams, home/away, lineups, provenance) comes first, then `MA3` events. `timeStamp` is wall-clock UTC; `timeMin`/`timeSec` is the Opta match clock (continues through added time; period 2 starts at 45:00). Every message carries `synthetic: true` for generated data.

## Output 1: GraphQL (Data API builder, anonymous read)

Local: `http://localhost:5000/graphql`. Dev (Azure): `https://itg-etl-dev-dab.mangosmoke-bbf503ab.australiaeast.azurecontainerapps.io/graphql` (scales to zero, so the first request can take ~30 s; the database may also be resuming from auto-pause). All queries support `filter`, `orderBy`, `first`, `after`.

| Query | One row per | Use |
| --- | --- | --- |
| `matches` | match | Team names, `homeContestantId`/`awayContestantId`, full MA1 `payload` (lineups). |
| `rawEvents` | event | History. Typed columns plus full message in `payload` (qualifiers). |
| `keyEvents` | key event | Authoritative narrative ledger (see types below). |
| `minuteStats` | contestant, minute, window | Per-minute deltas. Usually prefer `matchStatsAsOfs`. |
| `matchStatsAsOfs` | contestant, match minute | Running totals as of the end of that minute. |

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

JSON body; application property `notificationType` (same value as `messageType`) for subscription filters; `MessageId` set for duplicate detection (delivery is at least once, so consumers should still be idempotent). Every message carries the same keys (`messageType messageId matchId periodId timeMin timeSec eventTime windowEnd id keyType detail typeId contestantId playerId relatedEventId`); keys a type does not use are `null`. Switch on `messageType`.

| messageType | Body fields | MessageId |
| --- | --- | --- |
| `KeyEventDetected` | the `keyEvents` row fields | `{matchId}:key:{id}` |
| `MinuteClosed` | `matchId periodId timeMin windowEnd` | `{matchId}:minute:{periodId}:{timeMin}` |
| `PeriodStarted` / `PeriodEnded` | `matchId periodId eventTime` | `{matchId}:{messageType}:{periodId}` |

- `MinuteClosed` fires when a match minute's window closes (after the late-arrival tolerance). No events, no window: nothing fires during half time.
- `MinuteClosed` and the SQL write for that minute happen together. If `matchStatsAsOfs` has no row for that minute yet, retry briefly.
- Replays can run faster than real time (`--speed 10` gives 6-second minutes), so don't assume 60 seconds per minute.

**Status:** deployed in dev and verified against the reference pipeline. Namespace `itg-etl-dev-0zvxh-sbns`, subscription `narrative-engine`; for now consumers authenticate with the listen-only key (`terraform -chdir=etl/infra output -raw servicebus_listen_connection_string`), to be replaced by Entra roles later. Offline, `python -m devtools load-local` writes the same message bodies to `etl/.local/notifications.jsonl`. Messages only flow while the Stream Analytics job is running and a replay is sending.
