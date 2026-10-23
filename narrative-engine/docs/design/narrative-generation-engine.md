# Narrative Generation Engine: Design and Implementation Plan

> **In short:** historical original design of the engine, no longer updated. Current behaviour: [overview](../overview.md) and [architecture](../architecture.md).

| | |
| --- | --- |
| **Status** | Historical design; superseded by the docs above |

Inside the Game hackathon (Microsoft). This document describes the narrative generation engine: what it does, how it fits with the other services, how match context is built, the agents and their prompts, storage, triggers, and the Azure infrastructure it runs on.

Scope: this document covers the narrative generation engine only. The ETL service and the user service are described only at the level of the interfaces the engine uses.

---

## 1. Purpose and core idea

The engine produces a live, personalised narrative for users watching a football match.

To scale to large numbers of users, narrative generation cannot rely on separate LLM calls for every user, as this becomes far too expensive. Instead, users are grouped into **user types**, and every user of the same type receives the same narrative.

Personalisation is only applied at the **final step** of narrative generation. The facts of what happened in a match don't change depending on who you support, so the minute summaries and context compressions are built **once per match** and shared across all user types. Only the narrative author step runs per user type. This:

- keeps costs down,
- guarantees every user type is working from the same set of facts,
- means a user type that tunes in late can have a narrative generated immediately from the shared context.

### 1.1 User type matrix

A user type is a combination of two categorisations:

| Dimension | Values |
|---|---|
| Team support | `home`, `away`, `neutral` |
| Experience level | `simple`, `casual`, `experienced`, `analyst` |

That gives **12 user types**. Regardless of how many users the application serves, there are at most 12 narrative excerpts generated per narrative step.

Narratives are **lazily generated**: only user types with at least one user currently tuning in get a narrative. Team support is inferred by the user service from the team the user supports (selected in the frontend) and the teams currently playing. The engine does not assign user types; it only receives the set of active types.

---

## 2. System context

The engine is one of three services. It talks to the others only through these interfaces:

| Direction | Interface | Purpose |
|---|---|---|
| In | Service Bus topic `match-notifications` | `KeyEventDetected` and `MinuteClosed` messages from the ETL |
| In | Service Bus topic `presence` | `PresenceChanged` messages from the user service (which user types are active) |
| Out (query) | ETL GraphQL API | Raw events, key events, minute stats, match stats as at a minute |
| Out (model calls) | Microsoft Foundry, via Microsoft Agent Framework | Summarise, compress, author |
| Out | Service Bus topic `narrative-created` | `NarrativeCreated` messages consumed by the user service |
| In (read only) | Cosmos DB `narratives` container | The user service reads narrative history directly, with read-only RBAC |

Notification arrives via the bus, data is fetched via GraphQL. Each does what it is good at.

The engine never talks to clients. The user service is the backend-for-frontend: it consumes `NarrativeCreated`, pushes excerpts to Web PubSub groups (one per `matchId:userType`), uses narratives as chat agent context, and drives the per-type stat ranking. None of that is the engine's concern.

### 2.1 What the ETL provides (interface only)

The ETL (Event Hubs, then Stream Analytics, then Azure SQL, exposed through Data API builder as GraphQL) provides:

**GraphQL queries**

| Query | Used for |
|---|---|
| `rawEvents(matchId, from, to)` | Minute summary input; raw events since last summary for the author |
| `keyEvents(matchId)` | The key event ledger |
| `minuteStats(matchId, from, to)` | Per-minute per-team deltas, if needed |
| `matchStatsAsOf(matchId, minute)` | Game state statistics now, or at the end of a compression window |

**Service Bus messages on `match-notifications`**

- `KeyEventDetected`: emitted for goals, red cards, penalties and VAR overturns.
- `MinuteClosed`: emitted when a 1-minute tumbling window closes, after the late arrival tolerance. This is the watermark. It means "all events for this minute are in", so the engine can safely summarise that minute.

The ETL owns key event extraction and stat snapshots. Snapshots are computed at read time by summing per-minute deltas, so the stats as at any minute are always available. VAR overturns write negative deltas (e.g. `goalsDelta = -1`) so sums stay correct.

Known ETL caveats the engine must tolerate:

- Minutes with no events produce no window, so **no `MinuteClosed` arrives during half time**. Half-time logic must not wait for one.
- Kickoff is aligned to a wall-clock minute so tumbling windows match match minutes.

---

## 3. Engine internals

The engine is a Python service on an Azure Container App. Logical components:

| Component | Responsibility |
|---|---|
| **Notification Listener** | Subscribes to `match-notifications` and `presence`. Hands messages to the orchestrator. |
| **Match Orchestrator** | Owns the match clock, compression rules, author triggers, the active user type set, and checkpoints. Decides what runs when. |
| **Match Data Client** | Thin GraphQL client for the ETL API. |
| **Context Builder** | Assembles the author's context: non-superseded context blocks, raw events since the last summary, the key event ledger, current stats, and the last N narratives for the user type. |
| **Agents** | Minute Summariser, Context Compressor, Narrative Author, called through Microsoft Agent Framework against Foundry deployments. |
| **Narrative Publisher** | Writes the excerpt to Cosmos `narratives`, then publishes `NarrativeCreated`. |
| **Narrative Store** | Cosmos DB for NoSQL. Containers `matches`, `contextBlocks`, `narratives`. |

### 3.1 Design principles

1. **Personalise only at the author step.** Summaries and compressions are factual, neutral and shared.
2. **Key events are never the LLM's responsibility.** They come from the ETL as a structured ledger and are passed verbatim to the author. Summaries carry the story, not the ledger. This means a compression of compressions can never drop or mistime a goal.
3. **The author always sees the triggering event.** If a goal triggers the author at 23:40, the 23rd minute summary doesn't exist yet, so raw events since the last summary are always appended to the author context.
4. **Stateless agent calls.** Context is constructed, not conversational. Do not use Agent Framework threads as memory. Every call is built in Python from Cosmos and GraphQL data and passed in. This keeps runs reproducible, debuggable and restart-safe.
5. **Structured JSON output** from all agents where the output is parsed (summariser and compressor). The author returns the excerpt text only.
6. **Deterministic context tiling.** The context is always "every non-superseded block, ordered by time", with no special-case logic.

---

## 4. Match clock and timing

- Match time is tracked as a tuple **`(period, minute, addedMinute)`** rather than strings like `45+1'`. This handles stoppage time consistently. Periods: first half, second half, and (if supported) extra time halves and shootout.
- Minute summaries are driven by `MinuteClosed` from the ETL, not by a local timer, so they never run before all the minute's events have landed.
- **Half time:** no minute summaries are produced. The break is used to run any outstanding compressions and can optionally trigger a half-time narrative step. Do not wait for a `MinuteClosed` during the break.
- **Extra time and shootouts:** decide whether the demo supports them. If not, end the match at full time of the second half.

---

## 5. Context construction

### 5.1 The problem

The naive approach feeds every minute summary so far to the author. This has two problems:

1. **Economics.** Token count grows very quickly. In the 80th minute there would be 80 summaries plus all previous narrative entries.
2. **Narrative focus.** Filling the context window with every minute gives equal weight to the whole game and pulls focus away from what is happening now. Earlier events still matter to later storylines, but spending proportionally more of the context window on the current state better guides the LLM towards what is relevant now.

### 5.2 The solution: decaying resolution

After a while, older one-minute summaries are less relevant, so the context compression agent merges them into larger time window summaries. This happens continuously in the background, so the context holds 6 to 10 of the most recent one-minute summaries, then progressively larger summaries for earlier periods.

### 5.3 Compression rules

1. When **11 minute summaries** are held, the oldest **5** are compressed into one **5 minute block**.
2. When **4 five minute blocks** are held, the oldest **2** are merged together with the existing **earlier match block** (if there is one) into a single earlier match block.
3. Every summary or block records the time window it covers. When it is compressed, it is marked as **superseded** by the new block.

The context window is therefore bounded at **one earlier match block, up to three 5 minute blocks, and 6 to 10 minute summaries**, no matter how long the match runs.

### 5.4 Worked example (first half)

| At end of minute | Action | Non-superseded blocks afterwards |
|---|---|---|
| 11 | Compress 1-5 | [1-5], m6..m11 |
| 16 | Compress 6-10 | [1-5] [6-10], m11..m16 |
| 21 | Compress 11-15 | [1-5] [6-10] [11-15], m16..m21 |
| 26 | Compress 16-20, now 4 five minute blocks, so merge 1-5 + 6-10 | [1-10] [11-15] [16-20], m21..m26 |
| 31 | Compress 21-25 (only 3 five minute blocks, so no merge) | [1-10] [11-15] [16-20] [21-25], m26..m31 |
| 36 | Compress 26-30, merge 1-10 + 11-15 + 16-20 | [1-20] [21-25] [26-30], m31..m36 |
| 41 | Compress 31-35 | [1-20] [21-25] [26-30] [31-35], m36..m41 |
| 45+1 | Compress 36-40, merge 1-20 + 21-25 + 26-30 | [1-30] [31-35] [36-40], m41..m45+1 |

Note: rule 2 counts only 5 minute blocks, not the earlier match block. Implement exactly as the rules in 5.3 state and verify against this table with a unit test that replays minutes 1 to 90+ and asserts the block set after each step. Key checkpoints from the original diagram: 1-5 at minute 11, 1-10 at minute 26, 1-30 at minute 45+1.

### 5.5 Building the author context

At any point:

```
context = all contextBlocks where matchId = M and supersededBy is null
          ordered by coversFrom
```

This always tiles the match from kickoff to now with no gaps or overlaps. The Context Builder then adds:

- current `matchStatsAsOf(matchId, now)`
- the full key event ledger `keyEvents(matchId)`
- `rawEvents(matchId, lastSummaryEnd, now)`
- the last N narratives for the user type (cap N, e.g. 5; the compressed context carries everything older)
- the trigger reason

---

## 6. Triggers and scheduling

| Trigger | Action |
|---|---|
| `MinuteClosed` | Run the Minute Summariser for that minute. Then run any compressions now due under 5.3. |
| `KeyEventDetected` | Immediately run the Narrative Author for every active user type, with the key event as the trigger reason. |
| 10 minutes since last narrative step, no key event | Run the Narrative Author for every active user type. |
| `PresenceChanged` | Update the active user type set. If a type goes from 0 to 1+ viewers, run an immediate catch-up author step for that type only. |
| Half time | Run outstanding compressions. Optionally run a half-time narrative step. |
| Full time | Final narrative step, mark match complete. |

### 6.1 Key events fire immediately (no debounce)

Key events trigger the author straight away, so users get the narrative for a goal or red card as quickly as possible. There is deliberately no debounce window.

The accepted consequence: a goal followed by a VAR overturn produces two narrative steps. The first celebrates (or laments) the goal; the second is a corrective excerpt triggered by the `VarOverturn` event. This is fine, and mirrors how a live commentator would react. The key event ledger is authoritative, so the second author run sees both the goal and the overturn and can write accordingly ("United thought they'd scored, but VAR rules it out").

Because author runs can now arrive close together:

- **Serialise author runs per user type.** If a second key event arrives while the author is still running for a type, queue the second run for that type rather than running both in parallel. This keeps `seq` ordering correct and ensures the second excerpt sees the first in its "last N narratives".
- Different user types still run in parallel with each other.

### 6.2 Single active scheduler

Run the engine as **one replica** (min = max replicas = 1), or use a Blob lease for leader election. Two replicas would double-fire every trigger.

### 6.3 Checkpoints and idempotency

Persist scheduler state in the `matches` container: last summarised minute, compression state, last author step time per user type. On restart mid-match, resume from the checkpoint rather than re-running.

Service Bus delivers at least once, so handlers must be idempotent. Use deterministic document IDs (e.g. `summary:{matchId}:{period}:{minute}`) so a duplicate `MinuteClosed` overwrites rather than duplicates.

---

## 7. Agents

All three agents are called through **Microsoft Agent Framework** (Python SDK) against **Microsoft Foundry** model deployments.

| Agent | Runs | Shared or personalised | Model | Output |
|---|---|---|---|---|
| Minute Summariser | Once per `MinuteClosed` | Shared | Small, fast deployment | `{"summary": "..."}` |
| Context Compressor | Per compression rule | Shared | Small, fast deployment | `{"summary": "..."}` |
| Narrative Author | Per trigger, per active user type (parallel) | Personalised | Stronger deployment | Excerpt text only |

`{$key_event_list}` (goal, red card, penalty, VAR overturn) is used only by the Python service and ETL to decide what goes into the ledger and what triggers the author. It does not appear in any prompt.

The Python service already knows the time window it asked for, so it stamps `coversFrom` / `coversTo` on stored blocks itself. The agents don't return them.

Prompt templates should be stored as versioned files (in the repo and/or Blob Storage). Record the prompt version on every stored block and narrative.

### 7.1 Minute Summarisation Agent

The minute summarisation agent is called once per minute, and its output is shared across all user types. The purpose of this agent is to produce a factual summary of what has happened in the past minute of match play by looking at the minute's events and the current game state statistics, e.g. home team maintained possession with 100% pass completion, play stopped for an injury to away player #5, etc. Key events are tracked separately in the key event ledger, so this agent does not need to record them, although they can be mentioned where they are part of what happened in the minute. As this agent runs every minute and produces short factual output, it uses a small, fast model deployment.

```text
You are a football (soccer) event data minute summarisation agent. You are part of a broader system that constructs football narratives live using a live match event stream and set of current game state statistics. Your role is to look at all the events that have arrived in the past minute, along with the current game state match statistics and make a brief summary of what has transpired in that minute. There is a separate agent that will use these summaries to construct personalised narratives on a schedule or when a major event happens. Your summaries are shared across all users, so they must be neutral and factual. Do not take the side of either team and do not add opinion or storytelling.

Key events such as goals, red cards, penalties and VAR overturns are recorded separately by the system, so you do not need to list them or track their timestamps. Focus on describing the flow of play in the minute. You can mention a key event where it is part of that story.

Your response should be brief, and use the following JSON structure:

{
  "summary": "Brief factual summary of the last minute."
}

Some examples of a good summary include:
- Home team (Forgeham United) maintained possession for most of the minute, completing all 15 of their passes. This is against the run of play, as away team (Port Albion) has had 62% possession so far.
- Away team (Port Albion) won a penalty after sustained pressure in the box, but it was saved by home team goalkeeper Halloran.

The current game state match statistics are as follows:
{$game_state_statistics}

The events from the previous minute are as follows:
{$match_events[curr_time - 1, curr_time]}
```

### 7.2 Context Compression Agent

The context compression agent is called on a schedule as defined in section 5.3, and its output is shared across all user types. The purpose of this agent is to compress minute summaries (or earlier compressions) from earlier in the game into summaries for larger time windows, keeping the key storylines between minutes while trimming the fat. Key events are tracked separately in the key event ledger, so this agent does not need to preserve them. Like the minute summarisation agent, it uses a small, fast model deployment.

```text
You are a football (soccer) data context compression agent. You are part of a broader system that constructs football narratives live using a live match event stream and set of current game state statistics. Your role is to take a set of summaries covering consecutive time periods, along with the game state statistics at the end of the time window you are looking at, and combine and compress them into a single larger time window summary that stitches together the key narratives over that period. The input summaries may be one minute summaries, or earlier compressions of longer time periods. Your compressions are shared across all users, so they must be neutral and factual. Do not take the side of either team.

Key events such as goals, red cards, penalties and VAR overturns are recorded separately by the system, so you do not need to list them or preserve their timestamps. Focus on the storylines that develop across the time window, such as momentum shifts, periods of pressure, and how each team is playing. You can mention a key event where it is part of that story.

Your response should be brief, and use the following JSON structure:

{
  "summary": "Brief factual summary of the time window, focusing on the storylines that develop across it."
}

Some examples of a good summary include:
- Away team (Port Albion) dominated this period with 67% possession and 4 shots on goal, and were unlucky not to score after a saved penalty. Home team (Forgeham United) spent most of the period defending deep in their own half.
- An even opening 10 minutes. Both teams traded spells of possession, with home team (Forgeham United) producing the only shot on target.

The game state match statistics at the end of this time window are as follows:
{$game_state_statistics[time_window]}

The summaries for this time window are as follows:
{$summaries[time_window]}
```

### 7.3 Narrative Author Agent

The narrative author agent is called immediately after every major event, and 10 minutes after every previous call if no new calls have been made. It is the only personalised agent, and is called once for each user type that currently has at least one user tuning in. It uses the constructed match context, the key event ledger, any raw events since the last minute summary, the current game state statistics and the most recent narrative excerpts it has created for this user type, to author the next excerpt. As this is the output users actually see, it uses a stronger model deployment.

```text
You are a football (soccer) data narrative author agent. You are part of a broader system that constructs football narratives live using a live match event stream and set of current game state statistics. Your role is to create a narrative excerpt that the user watching the game will see. Previous agents have already constructed for you a factual game context, which will include minute to minute summaries of match events for recent time periods, and larger time window summaries for earlier moments in the match. You will also have access to a key event ledger, any raw events that have happened since the last minute summary, the current game state statistics, and the most recent narrative excerpts that you have created for this user type.

The key event ledger is the authoritative record of key events. If it conflicts with anything in the match context, trust the ledger. If this narrative step was triggered by a key event, the triggering event will be in the raw events and should be the focus of your excerpt.

It is important that the new narrative excerpt you create flows on from the previous excerpts naturally, however you should not directly reference the previous narrative excerpts in your output.

You are forming these excerpts for a specific user type. A user type is comprised of a combination of their team support (home, away, neutral) and their football experience level (simple, casual, experienced, analyst). Tailor your excerpt as follows:
- Team support: home and away fans should hear the story from their team's perspective and share in its highs and lows. Neutral users should get a balanced account.
- Experience level: simple users need plain language and no jargon. Casual users want the main storylines. Experienced users appreciate tactical observations. Analyst users want the statistics behind the story.

The user type you will be building narratives for is {$user_type}.

Your response should be brief, and should contain the narrative excerpt only. The following is an example for a neutral experienced user type:

That goal from the home team (Forgeham United) comes entirely against the run of play. A dominant away team (Port Albion) will be regretting those 6 missed shots they've racked up this half.

This narrative step was triggered by:
{$trigger_reason}

The current game state match statistics are as follows:
{$game_state_statistics}

The key event ledger is as follows:
{$key_event_ledger}

The match context created for you is as follows:
{$combined_match_context}

The raw events since the last minute summary are as follows:
{$match_events[last_summary_time, curr_time]}

The most recent narrative excerpts you have written for this user type are as follows:
{$narrative_excerpts[user_type, last_N]}
```

---

## 8. Narrative Store (Cosmos DB for NoSQL, serverless)

Why Cosmos: small JSON documents all scoped to a match (`/matchId` is a natural partition key), fast point reads and ordered queries within a partition, TTL, change feed if needed later, and serverless pricing suits bursty match-shaped traffic.

All containers are partitioned by **`/matchId`**. Raw events and the key event ledger are **not** stored here; they belong to the ETL and are read through GraphQL.

The shapes below are a starting point, not a fixed schema.

### 8.1 `matches`

One document per match. Scheduler state and checkpoints.

```json
{
  "id": "match:{matchId}",
  "matchId": "...",
  "homeTeam": "Forgeham United",
  "awayTeam": "Port Albion",
  "status": "live",
  "clock": { "period": 1, "minute": 23, "addedMinute": 0 },
  "lastSummarisedMinute": { "period": 1, "minute": 22, "addedMinute": 0 },
  "lastNarrativeStepAt": "2026-10-18T05:12:40Z",
  "lastAuthorRunByType": { "home:casual": "2026-10-18T05:12:40Z" },
  "activeUserTypes": ["home:casual", "neutral:analyst"]
}
```

### 8.2 `contextBlocks`

Minute summaries and compressions in one container.

```json
{
  "id": "block:{matchId}:{level}:{coversFrom}:{coversTo}",
  "matchId": "...",
  "level": 0,
  "coversFrom": { "period": 1, "minute": 1, "addedMinute": 0 },
  "coversTo":   { "period": 1, "minute": 5, "addedMinute": 0 },
  "sortKey": 1001,
  "supersededBy": null,
  "statsTime": { "period": 1, "minute": 5, "addedMinute": 0 },
  "summary": "...",
  "model": "small-deployment-name",
  "promptVersion": "compress-v2",
  "tokens": { "input": 812, "output": 74 },
  "createdAt": "..."
}
```

- `level`: 0 = minute summary, 1 = 5 minute block, 2 = earlier match block.
- `sortKey`: a numeric encoding of `coversFrom` (e.g. `period * 1000 + minute + addedMinute / 100`) so `ORDER BY` is simple.
- `statsTime`: the snapshot time used, for reproducibility. Stats themselves live in the ETL.
- Superseding: write the new block first, then set `supersededBy` on the merged blocks. Use a transactional batch within the partition so the tiling is never briefly broken.

### 8.3 `narratives`

```json
{
  "id": "narr:{matchId}:{userType}:{seq}",
  "matchId": "...",
  "userType": "home:casual",
  "seq": 7,
  "trigger": { "type": "keyEvent", "events": ["evt-123"] },
  "matchTime": { "period": 2, "minute": 67, "addedMinute": 0 },
  "text": "...",
  "model": "strong-deployment-name",
  "promptVersion": "author-v3",
  "tokens": { "input": 2410, "output": 96 },
  "createdAt": "..."
}
```

The user service reads this container with read-only RBAC to serve history on connect or reconnect. (If strict ownership is preferred later, replace this with a small read endpoint on the engine.)

---

## 9. Messages

### 9.1 Consumed

`match-notifications` (from ETL):

```json
{ "type": "MinuteClosed", "matchId": "...", "windowEnd": "2026-10-18T05:13:00Z", "eventCount": 14 }
```

```json
{ "type": "KeyEventDetected", "matchId": "...", "eventId": "...", "eventType": "Goal",
  "period": 2, "matchMinute": 67, "eventTime": "...", "team": "home", "playerId": "..." }
```

`presence` (from user service):

```json
{ "type": "PresenceChanged", "matchId": "...", "userType": "away:analyst", "activeCount": 3 }
```

### 9.2 Published

`narrative-created`:

```json
{ "type": "NarrativeCreated", "matchId": "...", "userType": "home:casual", "seq": 7,
  "matchTime": { "period": 2, "minute": 67, "addedMinute": 0 },
  "trigger": "keyEvent", "text": "..." }
```

The full excerpt is included in the message (it is small), so the user service doesn't need a round trip to Cosmos for live delivery. The engine always writes to Cosmos **before** publishing.

Each consumer has its own subscription per topic. Exact field names should be agreed with the ETL and user service owners.

---

## 10. Runtime flows

### 10.1 Each minute

1. `MinuteClosed` arrives for minute *t*.
2. Query `rawEvents(t-1, t)` and `matchStatsAsOf(t)`.
3. Call the Minute Summariser, store a level 0 block.
4. Check compression rules; for each due compression, query `matchStatsAsOf(window end)`, call the Compressor, write the new block, mark inputs superseded.
5. Update checkpoint.

### 10.2 Key event (e.g. goal)

1. `KeyEventDetected` arrives.
2. Read `activeUserTypes`.
3. For each active type, in parallel across types (with a concurrency limit), but serialised within a type: build context, call the Narrative Author.
4. For each result: write to `narratives`, publish `NarrativeCreated`.
5. Reset the 10 minute fallback timer.

### 10.3 Late-joining user type

1. `PresenceChanged` takes a type from 0 to 1+ viewers.
2. Run an immediate author step for that type only, using the shared context. No history is missing because summaries are shared.

---

## 11. Azure infrastructure (engine)

| Resource | Use |
|---|---|
| Azure Container Apps | Engine service, 1 replica |
| Azure Cosmos DB for NoSQL (serverless) | Narrative Store |
| Azure Service Bus (shared namespace) | Subscriptions on `match-notifications` and `presence`; publish to `narrative-created` |
| Microsoft Foundry project | Two deployments: small model (summarise, compress), strong model (author) |
| Microsoft Agent Framework (Python SDK) | Agent definitions and calls |
| Managed identity (Entra ID) | RBAC to Cosmos data plane, Service Bus, Foundry, Storage |
| Key Vault | Anything that cannot use managed identity |
| Application Insights (OpenTelemetry) | Traces, token usage per agent per match |
| Azure Container Registry | Engine image |
| Blob Storage (optional) | Versioned prompt templates, end of match exports, leader election lease |

### 11.1 Model quotas and resilience

- A goal with all 12 types active is a burst of 12 author calls at once. Watch per-deployment TPM quotas, use a concurrency limiter, and retry with exponential backoff on 429s.
- The user service's chat agent may also use Foundry. Use separate deployments (or at least separate quota) so a burst of chat traffic during a goal can't throttle the narrative author.
- Default content filters on.

### 11.2 Observability

Log per call: agent, model, prompt version, input and output tokens, latency, match time, user type. A "cost per match vs naive per-user approach" chart is a strong demo slide.

---

## 12. Suggested code layout

A starting point for the Python service:

```
narrative_engine/
  main.py                  # app startup, health endpoint
  config.py                # settings, deployment names, N
  listener.py              # Service Bus subscribers -> orchestrator
  orchestrator.py          # triggers, per-type author queue, scheduling, checkpoints
  compression.py           # pure functions implementing rules in 5.3
  context_builder.py       # assembles author context
  match_data_client.py     # GraphQL client for ETL
  agents/
    summariser.py
    compressor.py
    author.py
    prompts/               # versioned prompt templates
  store/
    cosmos.py              # matches, contextBlocks, narratives
  publisher.py             # NarrativeCreated
  models.py                # MatchTime, ContextBlock, Narrative, message schemas
tests/
  test_compression.py      # replay minutes 1..90+, assert block set (see 5.4)
  test_context_builder.py
  test_author_queue.py     # per-type serialisation of back-to-back key events
```

Keep `compression.py` pure (no I/O) so the schedule can be unit tested exhaustively, including stoppage time and half time.

---

## 13. Open questions

- N (number of previous narratives passed to the author).
- Whether the demo supports extra time and shootouts.
- Whether to generate a half-time narrative step.
- Final GraphQL field names and message schemas, to agree with the ETL and user service.
- Model choices for the small and strong deployments.
