# Adapters

> **In short:** every upstream lives behind one adapter: the Event Hubs and Service Bus consumers, ETL GraphQL (Data API builder), the engine's GraphQL, the feed's HLS playlist, the model and decision clients and the SPADL data reference. Services never import an SDK or a URL.

| | |
| --- | --- |
| **Code** | [`backend/adapters/`](../../backend/adapters/) |
| **Brokers** | Event Hubs `match-events` (group `user-backend`); Service Bus topic `narratives` (subscription `user-backend`); consume only |
| **GraphQL** | ETL DAB (`ETL_GRAPHQL_URL`), narrative engine (`NARRATIVE_GRAPHQL_URL`); allowlisted queries only |
| **Tests** | `test_multi_match.py`, `test_engine_history.py`, `test_spadl_contract.py`, `test_event_adapter.py`, `test_usage.py`, `test_recordings.py` |

## 1. Broker consumers

*In short: commit, then acknowledge.*

`match_stream.py`:

```text
feed ── Event Hubs match-events ──┬── backend: MA1 → LiveMatch, MatchEvent v2 → received events (clock, periods, ticker)
                                  └── ETL stream ── SQL ── DAB GraphQL ── backend (stats, SPADL actions, MA3 cards/goals,
                                                                                matches, watermarks)
narrative engine ── Service Bus narratives ── backend: per-match narratives
```

| Message | Handling |
| --- | --- |
| MA1 | Stored unless tombstoned or sent before a purge-all cut-off; starts a `LiveMatch` |
| MatchEvent v2 | Only for a known match; duplicates ignored; an out-of-order event is buffered until its gap fills or is recovered ([services §1](services.md#1-registry-stream-and-gaps)) |
| MA3, POS, MatchEvent v1 | Ignored (ETL's) |
| Invalid JSON or schema | Logged and skipped; the missing `seq` then becomes a gap |
| Engine narrative (`userType`, no `type`), follow clip (`type: FollowClip`) or key-event clip (`type: MomentClip`) | Saved for a known match before completion; duplicates ignored; `IntegrationProbe` completed; anything else dead-lettered |

Positions: the last committed Event Hubs sequence number per partition is stored in `stream_checkpoints` after each batch commits, and held back while a gap is open. A partition without a stored position starts now (`MATCH_EVENTHUB_START=earliest` reads the retention; tombstones keep purged matches out). A position past a recreated hub's end (the emulator restarts at 0) is checked at connect and every 5 s while connected: it is logged, its stored position deleted, and the partition reconnects from now (or the retention with `earliest`). A database outage retries the same batch; narrative persistence retries under the renewable lock.

## 2. ETL GraphQL

*In short: matches, watermarks, stats and SPADL actions at a seq, MA3 cards and goals, and a canonical event for gap recovery.*

`etl_dab.py` holds one pooled `httpx` client per event loop and these queries:

| Query | Use |
| --- | --- |
| `matches(filter: {matchId: {in}})` (+ teams, players) | Match info; read once per match |
| `matchWatermarks` | Latest committed canonical `seq` and SPADL `spadlSeq` per match |
| `executeStatsAtSeq(matchId, seq)` | The stat catalogue at a snapshot (`seq ≤ spadlSeq`); empty means retry |
| `spadlActions(filter: {matchId, finalSeq: {gt: from, lte: s}})` | New final actions since the last read, 1,000 per page in `actionId` order |
| `rawEvents(filter: {matchId, typeId: {in: [16, 17, 900]}, eventSeq: {lte: s}})` | MA3 goals, cards and VAR decisions (outside SPADL), bounded in the database by the indexed `eventSeq` column |
| `canonicalEvents(filter: {matchId, seq})` | Gap recovery only; when ETL has no valid row or errors, the gap is recorded |

Errors raise `EtlUnavailable`; callers turn it into `503 snapshot_unavailable` or retry. `ma3.py` maps MA1/DAB names to the backend's (capabilities, teams, branding, players, stat rows with `action_types` and `unavailable_reason` = ETL's definition when unavailable), MA3 card rows (`card:{id}`, colour from qualifiers 31/32/33) and `score()`: goals per team from MA3 goals and VAR overturns, used for scores because the catalogue's `goals` do not subtract overturns yet.

`match_data.py` is the match-data port, with small per-snapshot caches:

| Call | Returns |
| --- | --- |
| `capture(match, seq=None)` | Snapshot at `min(received seq, watermark seq, spadlSeq[, seq])`; syncs SPADL actions to it first |
| `stats(snapshot)` | ETL catalogue rows |
| `actions(snapshot, …)` | Final actions at the snapshot, filtered (`actionType`, `playerId`, `teamId`, `period`, `[start, end)`) and paged |
| `cards(snapshot)`, `score(snapshot, teams)` | MA3 cards / goals per team by `eventSeq ≤ seq` |
| `periods(snapshot)` | Period start/end video seconds from received events |

## 3. Narrative engine, HLS and health

*In short: read-only reads bounded to the snapshot.*

- `engine_history.py`: recaps from the engine's `contextBlocks` (by `tier`); the tail from the snapshot's SPADL actions; key events and key moments (goals and own goals, penalties, cards and dismissals) from actions and MA3 cards; storylines as the snapshot knew them (opened, beats and salience by then; status `resolved` only once its resolution is reached, otherwise `active`). All bounded to the snapshot.
- `hls_media.py`: reads the feed's played playlist at `FEED_HLS_BASE/{matchId}/live.m3u8`; its end is the furthest a replay may reach. The browser path is `/media/hls/{matchId}/live.m3u8` (`PUBLIC_HLS_BASE`).
- `health.py`: probes upstream `/health` URLs for `/dev/pipeline`; failures are data.

## 4. Model and decision clients, usage

*In short: Microsoft Agent Framework agents over a configured OpenAI-compatible endpoint, one model per role.*

`llm.py` builds every agent's client when `LOCAL_LLM_BASE_URL` and `LOCAL_LLM_MODEL` are set (locally a development endpoint; in Azure the Foundry deployment). `openai_client` is the one place the SDK client is made, with SDK retries off so application retry limits stay exact. `role_model` picks each agent's deployment and effort from the `models` config row (`ROLE_OF`: questions, replay, follow_planner), else `LOCAL_LLM_MODEL` and `LOCAL_LLM_EFFORT`. A reasoning effort selects the Responses API (the only one that takes function tools with reasoning) with no temperature and `LOCAL_LLM_REASONING_TOKENS` more output; a chat model uses Chat Completions with temperature 0.

`decision.py` asks one yes/no question for the follow offer: Microsoft-Decision-1 via `DECISION_*` (the engine's envelope), else the question model constrained to yes/no. Values are never logged. `usage.py` counts tokens, calls and seconds per question and never records the model or provider.

## 5. SPADL reference

*In short: what the data means, checked against the action model and generated from ETL's contract.*

```text
etl/contracts/spadl-action.schema.json ─┐
etl/contracts/opta-codes.json ──────────┼─ devtools/spadl_reference.py ─▶ backend/contracts/spadl-reference.json
etl/reference/spadl.py (probed) ────────┘        (enums, field meanings, Opta source per type/result/body part)
feed_profiles/spadl-v1.json ── feed_reference.py ─▶ data reference ─▶ agents (+ match_reference: MA1 availability)
```

- `feed_profiles/spadl-v1.json`: one-line meanings per action type, result, body part, zone and family, plus outside-SPADL facts (cards, possession). `feed_reference.py` fails if any key set differs from the model's enums or fields.
- `match_reference.py`: adds `availability` from MA1 (`complete_bodypart_types`, `recorded_bodyparts`, `shot_outcomes`, `locations`) and only the capability keys rules need.
- `services/spadl_lookup.py`: `lookup_spadl(term)` for the question and replay agents: definition, Opta source, catalogue stats using it and a goal example, capped at about 300 tokens.
- Regenerate after an ETL contract change: `python -m devtools.spadl_reference` (from `user-backend/`); `test_spadl_contract.py` fails while it is stale.
- The synthetic recordings' key adapter is a test double in `benchmarks/doubles/events.py`; the runtime parses MatchEvent v2 with `models/match_stream.py`.
