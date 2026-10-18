# Main user backend: agreed architecture

Recorded **18 October 2026, Australia/Brisbane**, from the architecture discussion; updated during the repository-structure review to use Event Hubs for live events and Service Bus for new narratives. This is a planning record, not an implementation or deployment claim. Later decisions in the discussion supersede the initial diagrams.

The user backend connects the frontend to match intelligence. It answers viewer questions, manages profiles and viewing sessions, routes bucket narratives, selects default stat cards and builds custom statistics. The neutral match analysis and narrative engines remain outside this backend.

**Latest boundary decision:** ETL calculates standard statistics and stores their current state in its Cosmos DB. Historical events remain in ETL-owned event storage (Azure SQL in the current plan). Both are accessed through ETL GraphQL. The user backend selects and delivers standard values; it does not rebuild them from events. Only a genuinely custom request may require backend calculation.

## 1. Scope and phases

| Phase 1: hackathon | Phase 2: later version |
| --- | --- |
| One match, viewed live, with multiple demo viewers | Pause, rewind and delayed viewing |
| Selectable demo profiles; no sign-in | Playback-aware narrative and stat delivery |
| Two frontend tabs: agent chat and narrative feed/backlog | Answers constrained to playback time unless live information is requested |
| Bucket-specific narratives and changing default stat selections | Jev matching incoming narratives to explicit viewer subscriptions |
| Question agent and specialist coding agent | Highlight and “last X minutes” replay requests |
| Custom calculations, tested functions, live pinned stat cards | Ordered video segments returned for frontend playback |
| Reconnect recovery and one active session per profile | Pinned stat values and bucket selections restored when rewinding |

Phase 2 is shown in **grey or dashed styling** in service diagrams. It is not part of the first-version implementation.

## 2. System boundaries

| Component | Responsibility |
| --- | --- |
| Match event pipeline | Supply timestamped football events, computed stats and historical data. It does not execute viewer-generated stat functions. |
| Neutral analysis/narrative engine | Independently analyse the match, produce bucket-targeted narrative variants, deduplicate narratives upstream and issue changes to bucket stat selections. |
| ETL GraphQL | Expose precomputed stats from ETL Cosmos DB and raw/key event history from ETL Azure SQL. The backend never connects directly to either database. |
| Narrative GraphQL | Expose narrative history and current bucket selections; owned by the narrative service. |
| Live feeds | Event Hubs supplies match events; Service Bus supplies new narratives and stat-selection instructions. |
| Main user backend | Read demo profiles, resolve match preferences, answer questions, coordinate coding work, manage custom stats and sessions, and deliver updates to viewers. |
| Isolated generated-code executor | Run generated Python/filter logic with a fixed library set and controlled access to read-only GraphQL. |
| Frontend | Show match footage, stat cards, agent chat and the narrative feed; submit questions and user actions. In Phase 2, fetch and play requested video segments. |

**Viewer questions never prompt, inject into or trigger the neutral narrative engine.** “How is Chelsea going?” is answered by the question agent using available facts and narratives. It does not create a personal narrative workflow.

Narrative deduplication is explicitly outside this backend. Do not add a parent-insight deduplication subsystem here. Transport/event replay protection needed for accurate stat calculations is a different concern.

## 3. Demo profiles and viewing sessions

- Build selectable demo profiles containing a supported team and fan style. These simulate the account/profile data; there is no existing PL account service to integrate with for the demo.
- Read profiles directly from the Accounts database in the main backend. No separate account API/service is needed for Phase 1.
- Default the match experience from the selected profile. If their team is not playing, the viewer may be asked which team they support for this match.
- Viewers may change team choice or fan style during the match, but that control is not prominent. Apply the new bucket to the feed and default stats.
- Allow **one active viewing tab/session per profile**. A new tab takes over and terminates the previous active session.
- Restore saved chat and pinned stats after refresh/reconnection. Phase 1 resumes the live match; restoration of an earlier playback position belongs to Phase 2.
- Work already started on an answer/calculation continues after disconnect and saves its result. Do not implement cancellation merely because the connection closed.

## 4. The twelve buckets

`Team A / Team B / neutral` × `Analytical / Simple / Casual / Experienced`.

These are the agreed viewing presets. Preserve the names; do not substitute other audience dimensions.

### Narratives

The narrative engine emits **up to twelve bucket-specific narrative versions** for an insight. It may emit fewer, such as four versions relevant only to one team's viewers. Each version already identifies its target bucket.

The user backend routes the supplied versions to the appropriate viewers. It does not generate the bucket wording or run one narrative agent/workflow per viewer.

Mid-match joins and reconnects can retrieve the narrative backlog and current bucket configuration through GraphQL. The frontend has one tab for agent chat and another for the narrative feed, including its backlog.

### Default stat cards

- Each bucket begins with a predefined, ranked selection from an approved pool of existing statistics. ETL owns their calculation, corrections and stored values; the backend does not independently aggregate them.
- Read standard values through ETL GraphQL whether they are used on a card or in an agent answer. Ordinary card refreshes do not fetch raw match history.
- The narrative engine can send a structured **“new stats” instruction** containing the target bucket and a new priority-ordered list, such as goals and cards.
- The backend recognises those names and resolves their existing state fields through GraphQL: conceptually, `goals → state:goals`. This is a mapping example, not a final GraphQL schema.
- The selection remains until a replacement instruction arrives. Roughly four changes per match was discussed as an expectation, **not a fixed schedule or a backend-owned periodic selector**.
- The backend preserves custom pinned slots when default selections change.
- These instructions have effective match timestamps. In Phase 2, rewinding restores the targeted stat selection appropriate to that point, as well as its values.

## 5. Agent responsibilities

**Microsoft Agent Framework with models from Microsoft Foundry is locked in** for the question and coding agents. Model/deployment names are not yet selected.

### Question agent

The question agent handles the viewer conversation, uses computed stats and match context, and consults history where needed. It can answer about either team regardless of the viewer's bucket.

Before requesting code, it:

1. Understands the semantic goal: what exactly should be counted or calculated, for which entities and over what period.
2. Asks the viewer to clarify ambiguity that would change the result, such as headed touches versus headed shots.
3. Checks ETL GraphQL for an existing statistic that answers the request, including its team/time scope. Reuse it when available; do not generate a duplicate calculation.
4. For a historical investigation, query specific events through ETL GraphQL with the needed filters and pagination. Reading/searching events does not automatically require a coding agent.
5. Only if a new calculation is needed, checks data availability, defines the goal and expected result, then delegates to the specialist coding agent. Explain unsupported requests immediately.

It may automatically request and run a custom calculation to answer a question. **Pinning that result as a live stat is a separate viewer choice.**

### Coding agent and test harness

The coding agent receives the goal from the question agent. It writes the custom function, checks its output against that goal through a test harness and repairs failures. There is **no additional checking agent**.

The agreed sequence is **semantic goal/data check → function generation → result validation**. Validation must check the requested meaning and result, not merely whether the code executes.

Allow up to **three repair attempts after an initial failure**. If still unsuccessful, tell the viewer the stat could not be calculated. Do not pin an unvalidated function.

The viewer waits for the result; the chat does not proceed concurrently with another question while this work runs. Existing narratives and stat updates can continue. If the viewer disconnects, finish and save the answer for reconnection.

Validate before use and then trust the function. **There is no ongoing semantic rechecking of successful functions.** Execution errors are still detectable and can enter the repair path; plausible but incorrect later results will not automatically be identified. The exact test fixtures, semantic assertions and runtime failure presentation remain implementation details.

## 6. Custom stat functions

The agent can generate **Python, regex and other extraction/filter logic** supported by the runtime. This is more flexible than choosing only from a fixed menu of predefined stat operations.

Execution constraints:

- Functions live in this user backend system, not in the upstream match pipeline.
- Run generated code in an isolated executor, separate from the main backend process/container.
- Use a **fixed set of installed libraries**; no agent-driven installation of arbitrary packages.
- Permit read-only GraphQL queries through a controlled helper. The backend handles credentials, pagination and query limits.
- Do not permit upstream writes or arbitrary external-service access.
- Retain successful generated functions for reuse **within the current match only**.

First reuse an ETL-provided statistic if its meaning and time scope match. Otherwise, for a custom “headers this game,” calculate from kickoff. For “headers since minute 20” or “headers this second half,” generate the appropriate time filter. Backfill from raw match history, then maintain the value using new events.

Equivalent requests with the same match, entities, filters and time range **reuse one calculation**. Each viewer's pin points to that shared calculation; it does not start an identical worker or upstream event subscription. How equivalent generated functions are recognised remains to be designed; do not assume similar wording proves equivalence.

### Live data path

Use a shared match-event subscription for active custom calculations, rather than one upstream subscription per viewer. GraphQL supplies computed stats for ordinary context and a historical route to actual events for custom calculations.

The user backend consumes live match events directly from **Event Hubs**, with one shared consumer for this match. ETL GraphQL supplies history and computed stats. A GraphQL subscription bridge or separate sidecar is not required for the agreed path.

History-to-live handoff, reconnects and shared calculation state must avoid missed or double-counted events. Event IDs/replay positions and correction handling are implementation contracts to resolve with the pipeline, not already confirmed features.

## 7. Pinning and card replacement

Custom stat subscriptions are **continuously updated cards**, not threshold alerts. For example, subscribing to the number of headers keeps that count on screen.

| Viewer action | Behaviour |
| --- | --- |
| Pin a custom stat | Replace the lowest-priority visible bucket-default stat. Keep the total visible card count unchanged. |
| Pin another while default cards remain | Replace the next lowest-priority visible default. |
| Pin another when every slot is custom | Ask which existing custom pin to replace. |
| Remove a custom pin | Restore the highest-priority missing default from the current bucket selection. |
| Receive a new bucket stat selection | Update the default slots while preserving custom pins. |

Active custom subscriptions are scoped to the current match and end at match end for the live-only demo. Generated functions are not retained as a cross-match library. The exact number of visible stat cards is not yet chosen.

## 8. Frontend communication and persistence

Use individual API requests for chat and actions such as pinning, plus **one live connection per active viewer session** for narratives and stat updates. Chat replies may stream. Both interfaces belong to the same main backend container; separate communication paths do not imply separate services.

The development harness uses HTTP and WebSocket; the production managed-transport choice is not locked in. SignalR appeared in an earlier diagram as a proposal, not an accepted requirement. Upstream transport is now agreed: Event Hubs for match events, Service Bus for new narratives, and service-owned GraphQL APIs for history. Audience-presence feedback remains an open question; no feedback from viewer questions is sent to narrative generation.

Use **two databases on the same database server**:

| Database | Owned data |
| --- | --- |
| Accounts | Demo profiles, supported team and fan style. |
| Match App | Chat, match-specific preferences, pins/subscriptions, generated functions, validation outcomes, calculation state and viewing sessions. |

Match facts/history and canonical narratives remain upstream and accessible through GraphQL. Do not turn this database into another authoritative match-event or narrative store. Temporary caches/checkpoints may support execution and recovery.

For Phase 1, database state lets us restore viewer configuration and completed answers. Work continuing after disconnect must not depend on keeping the original frontend request connected. Durable job execution across backend restarts is a separate implementation choice, not a confirmed product requirement.

## 9. Phase 2: semantic subscriptions with Jev

Jev refers to **TypeSafe's decision model**, not a model gateway. This feature is deferred to Phase 2.

- A viewer explicitly asks to follow an interpretive interest. An ordinary question does not silently create a subscription.
- Jev checks **new narratives as they arrive** against active requests. It does not periodically inspect match stats looking for a narrative to create.
- Viewer requests never feed back into the neutral narrative engine.
- A match displays an **existing supplied narrative**, labelled to show it is linked to the viewer's request. Do not make a separate LLM call to write a personal update.
- An explicit subscription overrides the usual bucket filter: a viewer may receive a relevant insight targeted at another bucket.
- This does not change the upstream engine's ability to produce bucket-specific wording. “Neutral” here preserves the supplied content and independent match interpretation; it does not introduce user-specific rewriting.
- Subscriptions are match-scoped. Choice among multiple matching bucket versions and the delayed-viewing expiry behaviour remain Phase 2 details.

## 10. Phase 2: replay and playback-aware behaviour

The viewer can ask for a highlight or the last X minutes. The backend resolves the requested footage and returns an **ordered list of video source IDs and start/end timestamps**. The frontend fetches and plays those segments using the streaming source. Do not generate temporary stitched video files for this design.

Match events already carry timestamps. Mapping those to the video's time reference is considered feasible; the exact event-to-video clock mapping still needs to be defined.

For paused, delayed or rewound playback:

- Narratives and stat values follow the viewer's playback position.
- The question agent only uses information available up to that position, unless the viewer explicitly asks for the live situation.
- Custom pins remain selected but recalculate as of the earlier position.
- Bucket-default stat selections also rewind, using the narrative engine's timestamped selection changes.
- Shared calculations must support the values needed at different viewer playback positions.
- Reconnection restores the saved playback position as well as chat and pins.

All of this moved to Phase 2 when the hackathon scope was narrowed to live-only viewing.

## 11. Azure service plan and remaining choices

| Area | Current decision/status |
| --- | --- |
| Agent orchestration | **Locked:** Microsoft Agent Framework. |
| Agent models | **Locked platform:** Microsoft Foundry; exact models/deployments pending. |
| Backend hosting | User delegated the Azure choice; **selected: Azure Container Apps** for the Python backend. |
| Database | User delegated the engine choice; **selected: Azure Database for PostgreSQL Flexible Server**, with Accounts and Match App databases on one server. |
| Generated-code isolation | **Required boundary**, but sandbox/runtime technology and resource limits still to be selected. A separate ordinary process alone is not the isolation specification. |
| Frontend live transport | One live connection agreed; direct streaming versus managed transport still to be selected. |
| Blob Storage | Not needed for the agreed Phase 1 application state; optional future archive/export storage only. |

Other implementation details remain open: the fixed Python package list, GraphQL schemas and Event Hubs consumer configuration, backfill/replay contract, agent models, result-validation method, calculation-equivalence key, and exact card count. These are not permission to expand the agreed product scope.

Service references used during planning: [Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/overview), [Azure PostgreSQL](https://learn.microsoft.com/en-us/azure/postgresql/overview), [PostgreSQL JSON types](https://www.postgresql.org/docs/current/datatype-json.html), [GraphQL subscriptions](https://graphql.org/learn/subscriptions/), [TypeSafe Jev](https://docs.typesafe.ai/introduction).

## 12. Review scenarios for implementation

1. Select a demo profile mid-match: load its bucket, narrative backlog, latest ranked stat selection and ETL-computed values, without fetching raw history or recalculating standard stats.
2. Ask an ordinary football question: answer without invoking or changing the neutral narrative workflow.
3. Ask for headers since minute 20: clarify if needed, check data availability, delegate code generation, validate and return a historical calculation.
4. Pin that result: replace the lowest-priority default and update its value as new events arrive.
5. Request the same stat from another profile: reuse the calculation and share its updates.
6. Receive a new bucket selection: refresh defaults while preserving pins; removing a pin restores the highest-priority missing default.
7. Exhaust the custom slots: ask the viewer which existing pin to replace.
8. Fail validation: provide up to three repair attempts, then explain failure without activating the function.
9. Disconnect during generation: finish and save the result; restore it and existing pins on reconnect at live play.
10. Open a second tab for the same profile: the new session takes over and the old session is disconnected.
11. Confirm Phase 1 excludes Jev semantic subscriptions, replay construction and playback-dependent querying.

These scenarios are acceptance targets for later implementation, not tests claimed to have passed.
