# Narrative engine contracts

What the user backend can rely on. Live narratives arrive on Service Bus; this GraphQL API serves history for joins and reconnects. Inputs come from the [ETL contracts](../../etl/contracts/README.md).

## Output 1: GraphQL (narrative history, read-only)

**Deployed to dev** ([api.py](../narrative_engine/api.py)): `https://itg-narrative-dev-engine.mangosmoke-bbf503ab.australiaeast.azurecontainerapps.io/graphql`, anonymous read (synthetic data; LATER: restrict to the user backend). Locally: `python -m narrative_engine.api .local/narratives.jsonl` or `python -m narrative_engine.devtools.local <notifications> --serve 8000`, then `http://localhost:8000/graphql`.

| Query | Returns | Use |
| --- | --- | --- |
| `narratives(matchId, userType, afterSeq = 0, first = 50)` | One bucket's narratives with `seq > afterSeq`, oldest first, plus `hasNextPage` and `endCursor` (the last `seq`) | Backlog on join; gap fill on reconnect |
| `matchState(matchId)` | `status` (`live`/`complete`), `lastSummarised` match time, `activeUserTypes` | Which buckets are being written for; whether the match is over |

```graphql
query ($m: String!, $u: String!, $after: Int!) {
  narratives(matchId: $m, userType: $u, afterSeq: $after, first: 50) {
    items { id seq stepId triggerType triggerReason matchTime { periodId timeMin label } text createdAt }
    hasNextPage endCursor
  }
  matchState(matchId: $m) { status activeUserTypes }
}
```

- **`userType`** is `{support}:{level}`: support `home`, `away`, `neutral`; level `simple`, `casual`, `experienced`, `analyst` (12 buckets). Anything else is a GraphQL error, as is `first` outside 1–200.
- **`seq`** counts 1, 2, 3… per match and bucket, with no gaps. Keep the last `seq` you showed per bucket; on reconnect, ask for `afterSeq` = that value. Following `endCursor` while `hasNextPage` gets everything.
- **`stepId`** is shared by every bucket's version of one narrative step (a goal, half time, a scheduled update). `id` is unique and stable: `narr:{matchId}:{userType}:{seq}`.
- **`matchTime`** uses the ETL's Opta clock (`periodId`, 0-based `timeMin`) and its broadcast `label` (`45+2'`). A bucket only gets narratives while it is in `activeUserTypes`. A bucket that becomes active mid-match gets a `catchUp` narrative, then continues with the rest.
- `text` is plain text, one to three sentences. Stat-selection instructions are not produced yet.

## Output 2: Service Bus (live narratives)

**Implemented (phase 6), dev only.** Topic `narratives` in the ETL's Service Bus namespace (`narrative-engine/infra`), subscription `user-backend`. One message per narrative, written to Cosmos DB before it is sent. The body is the narrative document below (as in local `.local/narratives.jsonl`), with `MessageId` = `id` (the topic has duplicate detection) and application properties `userType` and `matchId` for subscription filters.

```json
{"id": "narr:demo:away:casual:3", "matchId": "demo", "userType": "away:casual", "seq": 3,
 "stepId": "demo:key:2700000390",
 "trigger": {"type": "keyEvent", "ref": "key:2700000390", "reason": "Key event at 24' (23:09): Goal for Riverside FC, Mensah", "eventIds": []},
 "matchTime": {"periodId": 1, "timeMin": 23, "label": "24'"},
 "text": "...", "model": "...", "promptVersion": "narrative-author.v2", "tokens": {...}, "createdAt": "2026-10-18T21:07:02+00:00"}
```

Delivery is at least once; deduplicate on `id`. If a `seq` is skipped, fill the gap from GraphQL.

## Input: presence (proposed)

**Implemented in the engine; needs the user backend's agreement.** Topic `presence`, subscription `narrative-engine`. A full-state message whenever the counts change, plus a heartbeat every 60 s:

```json
{"matchId": "demo", "activeUserTypes": {"home:casual": 12, "away:analyst": 3}, "sentAt": "2026-10-18T21:07:00Z"}
```

Messages older than the last applied `sentAt` are ignored. Without presence, or when the last message is over 3 minutes old, the engine writes for all 12 buckets.
