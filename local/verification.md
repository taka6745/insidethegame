# Verified locally — 2026-10-18

Machine: Apple Silicon macOS, Docker Engine 29.7.2, Compose 5.5.1. Existing unrelated containers were left running.

| Check | Result |
| --- | --- |
| `./dev up` + `./dev test` | Passed: Postgres profiles/two databases and Cosmos document round trip. |
| `ACCEPT_EULA=Y ./dev up azure` | Started: Event Hubs, Service Bus, SQL Server, Azurite and Data API builder. Licence acceptance explicitly authorised by the local user. |
| `./dev test azure` | Passed: SDK event send/receive, both Service Bus topic deliveries, SQL fixture seed and GraphQL history query. |
| `./dev replay` | Published the three synthetic fixture events successfully. |
| `./dev terraform check` | Passed: formatting, Azure provider schema validation and one mocked plan test with four boundary assertions. No Azure account or deployment. |
| Guide checks | Local Markdown links checked; SVG rendered and visually inspected. |
| Onboarding follow-up | `./dev doctor`, automatic checks on `up azure`, and invalid-mode/licence guards passed. Pinned image manifests checked for ARM64/AMD64 support where applicable. |
| Terraform follow-up | Passed without deprecated Event Hub fields, using the host user's UID/GID in Docker. |
| Fresh GitHub clone | Full `up azure` checks passed in a separate Compose project with empty volumes. No ignored workspace files or cached Terraform provider directory copied over. Docker image/build caches were reused. |
| Host connection examples | Both PostgreSQL databases, SQL, Cosmos, GraphQL, Event Hubs and Service Bus passed through the published host ports, using a Docker test client via `host.docker.internal`. GraphQL also queried directly from macOS. |
| Stop/start recovery | Fresh-clone stack passed `down` → `up azure` with SQL/Postgres volumes retained. Fixture seeding remained repeatable; all messaging/database checks passed again. Temporary test containers/volumes were then removed. |

These checks exercise actual local containers. They do **not** validate the Stream Analytics job, real Foundry models, application services, frontend, generated-code isolation or a cloud deployment. Terraform's mock-provider checks are also separate from runtime integration.

Re-run the commands on a new machine. Emulator behaviour differs from Azure; in particular messages/state, identity, throughput and resource-management APIs are not cloud-equivalent.

## User-backend harness — 2026-10-18

`./dev up backend` built and started the API, fake ETL and fake narrative services against the existing local Postgres. **39 tests passed**, including all 12 buckets, real database persistence/concurrent pins, session takeover, repeated socket disconnects, stat replacement, event corrections and the coding-agent repair contract.

The separate live smoke test replayed the JSONL through both fake services, read their GraphQL APIs and checked the backend WebSocket. It verified header count **4**, Chelsea goals **1**, United goals **0** after VAR, only the matching bucket narrative, duplicate-event protection and retained pins after session takeover. Tests use synthetic data; no model or Azure account was used.

One non-failing dependency warning: Starlette deprecates its HTTPX-based test client in favour of HTTPX2. The current pinned direct dependencies passed. Real agents, generated-code execution, production broker consumers and Azure deployment remain unverified/unimplemented; see [coverage limits](../user-backend/docs/development.md#4-tests).

## ETL stat ownership — 2026-10-18

`./dev up backend`: **42 tests passed**, followed by the live Docker replay check. New tests enforce unchanged ETL-provided standard values, no raw-history fetch for standard cards, and a separate event-history query for custom pins/investigation. Standard values are no longer redundantly calculated in the runtime backend adapter. Cosmos stat storage and SQL history remain the planned production ETL stores; these tests use the fake ETL GraphQL service.

## Product broker integration — 2026-10-19

`ACCEPT_EULA=Y ./dev up backend` passed **449 backend tests**, then both real AMQP integration checks. Event Hubs delivered recorded events to separate ETL/backend consumer groups. GraphQL snapshots agreed at video minutes 0, 1, 6 and 12; Service Bus delivered authored bucket narratives. A separate backend schema verified 12 custom-index events, a confirmed duplicate delivery without double counting, PostgreSQL restore and the durable narrative inbox. Both upstream HTTP checkpoint write paths returned 409. Active replay position and viewer sessions were preserved.

Upstream tests: **28 ETL passed, one optional database test skipped; 40 narrative passed**. The integration checks exercised the running ETL against PostgreSQL. A live API/WebSocket check switched audience and received 12 authored narratives plus five stat cards through the broker-backed runtime. Independent backend, upstream and wiring reviews completed after fixes.

The viewer returned HTTP 200. Browser inspection was blocked by the existing error-page tab's URL policy, so no fresh visual verification is claimed. This validates local Microsoft emulator adapters, not cloud deployment, distributed checkpoint leases, multi-replica operation or production load. See [transport and recovery limits](../user-backend/docs/components/adapters.md#1-broker-consumers).

## Native telemetry and full-frame camera — 2026-10-19

Rendered a new 720-second, 1280×720 Chelsea–United capture with a wider native camera, numbered shirt textures and no minimap. Extracted frames were visually inspected and FFmpeg decoded the complete video without errors. HTTP range delivery returned 206. Large video/raw assets remain ignored under `.local/grf-demo-chelsea-united-v3/`; the committed recording contains 1,376 deliveries.

Validation: **46 generator tests, 47 ETL tests, 41 narrative tests and 465 backend tests passed**; one optional ETL database test was skipped. Independent reviews covered native event attribution, presentation, stat availability and all twelve narrative intervals. The 144 bucket versions are bound to the exact new recording. Unknown body-part coverage remains unavailable rather than reporting incomplete header counts as totals.

A live WebSocket received 124 broker-delivered events, five ETL stat cards and the first matching authored narrative at roughly 60 video seconds. An isolated probe run concurrently with live replay correctly lost its stale snapshot's narrative publication; broker integration probes require idle replay. This is a test-harness sequencing requirement, not a change to production stale-message protection.

With replay idle, the real Event Hubs → ETL → Service Bus check passed at 0, 1, 6 and 12 video minutes, including duplicate delivery and all 1,376 history records. Isolated runs without matching viewer sessions correctly produced empty bucket payloads; the live viewer check above verifies nonempty narrative routing. Three probe-guard tests passed and the guard changes received a clean independent review.

The separate backend broker check passed: twelve indexed events, ignored redelivery, PostgreSQL restore, durable Service Bus inbox and rejected HTTP checkpoint writes. The demo was left ready at the beginning with the new recording loaded. These remain local emulator checks, not Azure deployment or distributed-load evidence.

## Three concurrent matches — 2026-10-21

`ACCEPT_EULA=Y ./dev up backend` rebuilt the stack and passed: **480 backend tests**, the ETL GraphQL check and all three broker probes. Then `./dev demo start chelsea-united arsenal-liverpool mancity-tottenham` kicked all three off together from 00:00. Two WebSocket viewers per match (`home:analytical` and `away:casual`) were followed for 23 match minutes.

| Check | Result |
| --- | --- |
| Clock | Never ahead of wall time since kickoff. The burned-in video clock matched the scoreboard (19:31). |
| Score and cards at 21:00 | Each equalled a count from that recording's MA3 stream at the same video second: goals, shots, passes (offside passes included), cards. City 1–2 Spurs: Bergvall 1:28 and 13:34, Bernardo 2:30, Bernardo booked. |
| Narratives | Only for buckets with a viewer (engine `activeUserTypes`). Key-event and 10-minute narratives arrived 9–49 s after their match clock. None was ahead of the viewer's snapshot clock. |
| Isolation | No message, narrative or event from another match in any socket. |
| HLS | Each match served played segments only; the next segment returned 404. `/media/match.mp4` returned 404. The viewer played video in headless Chrome. |
| Session takeover | Opening the same profile in a browser closed the older socket with 4001, by design. |

`./dev test backend` then passed while the matches ran: **486 tests** and every probe, with the running matches untouched. `./dev demo purge` removed 3 runs, 2,091 HLS files, 8,623 canonical events, 76 context blocks and 15 narratives. Nothing was left: no runs, no matches, no pins. Every prompt role stayed on its seed version.

## Config-only audiences, three matches — 2026-10-21 (round 3)

`ACCEPT_EULA=Y ./dev up backend` passed **508 backend tests** and every probe after DAB was recreated (it had kept the old config, without `canonicalEvents`; `./dev` now recreates DAB and the emulators when their mounted config changes). The orphaned `feed` database on the shared Postgres was dropped; the feed has its own server. `./dev demo start chelsea-united arsenal-liverpool mancity-tottenham` ran from 00:00 with two viewers on different matches and `/dev/` in headless Chrome.

| Check | Result |
| --- | --- |
| Dropdown | Listed only the 3 enabled buckets, with team names. Switching changed the narratives (Chelsea `home:analytical` → `neutral:simple`). |
| Enable / disable in `/dev/` | Arsenal: enabling `neutral:analytical` gave a catch-up 23 s later; disabled `away:casual` got no narratives. Open viewers received the new choices. |
| Descriptions in prompts | A marker added to the `neutral` option description appeared at the end of that bucket's next narrative only; then removed (the fixture inherits the default again). |
| Prices | Editing `prices` in `/dev/` re-costed the shown receipt from $0.011 to $0.110 within a minute; restored. |
| Profiles editor | A renamed profile showed in `/product/profiles`; restored. |
| Answers | Four questions on two matches. Pass counts equalled the recording at the viewer's seq (e.g. 198–186 at seq 2941), although the match had moved on by the reply. |
| Stats at 23:30 | Goals, shots, passes (offside included), corners and cards equalled the recordings at the snapshot seq on all three matches. |
| Service Bus restart | The emulator took 8.5 min to come back (host overloaded). The engine reconnected in-process (0 container restarts); the narrative whose publish failed was retried and delivered. |
| HLS | Played in Chrome; the next segment and `match.m3u8`/`match.mp4` returned 404. |
| `/health` | `gaps: []` throughout. |
| 10-minute narratives | 18–39 s after the match clock (second run, normal load). |

Found and fixed: after a host stall (load average above 200 from other work) the feed sent its backlog as one ~1,900-event batch. The Event Hubs emulator throttled it (1,000-credit limit) and stayed jammed; every retry was bigger, and HLS stalled with it. The feed now sends at most 200 items per call and publishes HLS while sends retry. A forced 150 s feed pause then recovered in about 10 s. Viewers also stopped reconnecting after 8 attempts; they now keep retrying every ~30 s.

Restarting the Event Hubs emulator resets its sequence numbers, so consumers need a restart and a new demo (see the README). `./dev test backend` then passed again: **510 tests** and every probe. Purged; templates, prompts, prices and profiles are at their seeded values.

## Three matches, round 5 — 2026-10-21

Host load average 30–100 throughout from unrelated work on the machine, so latencies below are pessimistic. `ACCEPT_EULA=Y ./dev up backend` passed **516 tests** and every probe (after the etl-stream fix below). Two runs of `./dev demo start chelsea-united arsenal-liverpool mancity-tottenham`, viewers in headless Chrome on Arsenal and Chelsea, plus WebSocket viewers.

| Check | Result |
| --- | --- |
| Pre-kickoff | A link opened before MA1 showed "Not open yet", then "KO in 0:52" … "KICK-OFF", then live, with video once the first segment played. |
| Dropdown, enable/disable | Enabling `neutral:analytical` (Arsenal, then Chelsea) gave a catch-up narrative about 2 min later; the dropdown changed without a reload; the disabled `away:casual` got nothing more. |
| Profiles | Renaming `fan_style` → `style` in the default template: profiles still listed, sessions still chose the right enabled bucket; saving profiles with the old layer was refused with a clear 422; editing them to `style=` saved. Reverted. |
| Leaderboards | "who has the most passes", "most shots for Arsenal", "most tackles" equalled the recording at the answer's snapshot seq (passes include offside passes). One timed out at 75 s under load; the retry answered. |
| Receipt | "2 facts · 26k tok · 40.9 s · $0.011" with the seeded prices. |
| Stats | Goals, shots, passes, corners and cards equalled the recording at the snapshot seq on all three matches (run 1, minute 58). Run 2 uses the new SPADL catalogue: passes can trail by one while the newest pass is unsettled. |
| HLS, `/health` | Only played segments; the next ones, `match.m3u8` and `match.mp4` 404. `gaps: []` throughout. |
| Event Hubs restart | Backend and etl-stream logged the reset and continued; a run started afterwards flowed. ETL lost the ~250 events per match it had not yet read and then counted past the hole (wrong score); fixed below. |

Found and fixed:
- etl-stream crashed at start (concurrent first imports of `azure.core` in two threads), and a reconnect could share the SQL connection with a finishing batch (pymssql abort). SDKs import at module load, `load()` takes the worker lock, compose restarts it on failure.
- ETL accepted canonical seqs past a hole, so stats silently undercounted after lost events. It now holds the watermark before the hole (one warning) and forgets stored checkpoints of a reset hub.
- ETL inserted rows one statement each and fell minutes behind under load; now multi-row inserts.
- Service Bus emulator stuck throttling (code 50002) for 35 min while SQL was saturated; a restart cleared it (README note). The old one-statement `statsAtSeq` used seconds of CPU per call; the SPADL rewrite (008) has since replaced it.
- Backend event loop near saturation: the data reference (JSON schema) was rebuilt and the whole history folded on every snapshot. Cached, and the feed uses the newest 600 deliveries.
- Viewer: a 503 right after MA1 showed "Offline" for good; it now keeps connecting. A live playlist that did not exist yet left the video blank; hls.js now gives up so the viewer re-attaches.
- `./dev demo purge` timed out at 60 s under load; 300 s now.

Purged; templates are at the seed (default only).

## SPADL live, round 7 — 2026-10-21

First live run of SPADL end to end. `ACCEPT_EULA=Y ./dev up backend` applied `009_spadl_stats_staged.sql` and passed **537 backend tests** and every probe ("126 stats served"); after the fixes below **538**. `ACCEPT_EULA=Y ./dev up azure` and `./dev test azure` passed. ETL suite in a throwaway container against SQL Server: **69 passed** (SQL and UDF tests included). Narrative engine: **104 passed**. Then `./dev demo start chelsea-united arsenal-liverpool mancity-tottenham` from 00:00, viewers on Chelsea and Arsenal in headless Chrome (separate windows), followed for 30 match minutes; load average 4–9.

| Check | Result |
| --- | --- |
| SPADL | Every 2 min on all three matches: `spadlSeq` within ~10 seqs of `seq`, equal once quiet; GraphQL `spadlActions` (`finalSeq ≤ min(seq, spadlSeq)`) equalled `etl/reference/spadl.py` on the received MA3 rows and the whole-recording conversion. |
| Stats | All 126 `executeStatsAtSeq` values equalled the reference catalogue on the recording at the same seq, every sample, every match. |
| Score header | Chelsea 1–0 (29′), Arsenal 1–0 (26′), City 1–2 Spurs (18′) as the recordings. |
| Narratives | Active prompts are the SPADL seeds (author and minute summary byte-equal to `migrations/prompts/`); 10-minute and key-event narratives use SPADL measures (crosses, box entries, shots on target, saves). |
| Questions | Crosses per team (6/1), Liverpool box entries (8), passes leaderboard (Timber and Frimpong 10), City–Spurs saves → `shots_saved` 0/1 (all save events → `saves` 2), "which goalkeeper has the most saves" → custom `save_kinds [save]` (Vicario 1): each equalled the reference at the answer's snapshot seq. |
| Tracked rule | "Successful tackles, Chelsea, first half" tracked; the card went 1 → 2 → 3 at the recording's tackles and survived a backend restart. |
| Replays | "Show me United's shots" and "show me the saves" gave 2 clips each with correct captions; the replay played in Chrome with the live picture-in-picture. |
| `/health`, HLS | `gaps: []` throughout. Next segment, `match.m3u8` and `match.mp4` 404. |
| `test_graphql_live.py` | 2 passed against the Chelsea run (after the goal). |

Found and fixed:
- DAB kept its startup schema after `009` added `spadlActions.fromShotOffTarget/defensiveBlock`; `./dev` now recreates DAB when an ETL migration changes.
- `etl/requirements-test.txt` lacked pymssql, so the SQL tests skipped silently (CI too).
- The backend's SPADL reference was stale (`devtools.spadl_reference` regenerated).
- `saves` counts every keeper_save (Chelsea–United 12, 9 real). New `shots_saved` (42nd kind, `keeper_saves` counter: both flags false) in 008/009, the reference, golden values and contracts §4; the backend gets `save_kind` (`save`, `wide_touch`, `block`) for custom rules and replays. Asked "how many saves", the model first reused `saves` (United 1, an outfield block); a deterministic guard now maps plain saves to `shots_saved` / `save_kinds [save]` (United 0 after redeploy).
- `test_graphql_live.py` compared SQL floats exactly.
- Headless note: a background tab pauses `requestAnimationFrame`, so its clock and video freeze until shown; use separate windows.

Purged (3 runs, 2,724 HLS files, 2,965 SPADL actions); no runs, matches or pins left; prompts unchanged.
