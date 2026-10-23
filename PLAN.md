# InsideTheGame: plan, decisions and progress

> **In short:** the living record of where the integration stands, what was decided and why, how the work is reviewed, and what comes next. It is updated as work lands. The submission closes 27 Oct 2026, 11:59 pm PT.

| | |
| --- | --- |
| **Branch** | `integration/luke-services`, pushed and merged to `main` |
| **Last updated** | 22 Oct 2026 |
| **Now** | Azure test (spend guard, three matches to half time, model experiment); Start demo build |
| **Next** | Demo build, phases D1–D4 (§10), then the Azure demo acceptance (§10.4) |

## 1. Goal

*In short: one production-shaped flow, local and Azure, from a simulated provider to the viewer.*

Wire Luke's ETL and narrative engine into the app as a full flow fed by our GRF match data:
- narratives only for the audience buckets the backend has enabled;
- prompts and tunables in the database, edited live in `/dev/`;
- several matches at once;
- deployable to Azure with one command.

## 2. Architecture (as built)

*In short: the feed is an external provider; Luke's pipeline is the only ETL; SPADL is the action language.*

```text
feed (simulated provider: recordings, MA1/MA3/POS/MatchEvent v2, HLS over HTTP)
  → Event Hubs (partition = matchId)
  → etl-stream (Stream Analytics stand-in) → SQL: rawEvents, keyEvents, minuteStats,
    possessionSamples, spadlActions (SPADL post-processor), statDefinitions, statsAtSeq
  → DAB GraphQL                         → Service Bus narrative-live
  → narrative engine (one worker per match; enabled buckets only; prompts from DB)
  → Service Bus narratives → backend (MatchRegistry per match; questions, replays, config)
  → frontend: match picker, viewer, lab, /dev/
```

| Service | Local | Azure |
| --- | --- | --- |
| Feed | Tested | Terraform written, plan passes, not applied |
| Event Hubs, Service Bus | Emulators | Terraform; was deployed, deleted 21 Oct to save credits |
| ETL (stream, SQL, DAB, SPADL) | Tested | Terraform + Stream Analytics query written, not applied |
| Narrative engine | Tested | Terraform; was deployed, deleted 21 Oct |
| Backend, frontend | Tested | Terraform written, plan passes, not applied |

`./dev azure up | down | status | plan` deploys or removes everything (Terraform in Docker, state under `.local/terraform/`). `down` stops Stream Analytics first, purges soft-deleted resources and confirms nothing billable is left.

## 3. Decisions

*In short: what was chosen, by the developer unless marked.*

| Date | Decision |
| --- | --- |
| 20 Oct | Never name the local development LLM provider, its hosts or model families in files. Azure AI Foundry and Azure model names are welcome; the judging rewards them. |
| 20 Oct | Real demos and showcases start from kickoff (00:00). |
| 20 Oct | Prod-ready: no stubs or hard-coded data on the live path; tunables live in the owning service's DB and `/dev/`; future data must be physically unreachable. |
| 20 Oct | Several matches run at once; every layer is keyed by a run-scoped `matchId`; purge is per match. |
| 20 Oct | The feed simulates an external provider: our services see only Event Hubs and HLS over HTTP. |
| 20 Oct | Unify on Luke's ETL; the demo ETL stand-in is deleted. |
| 20 Oct | New recordings use named clubs and players (replaced by the fictional Elephant League on 23 Oct, §12 M6). |
| 20 Oct | No "sides": the whole codebase is ours to fix, including ETL, engine, Azure infra and telemetry. |
| 21 Oct | Audiences are config-only: layers → buckets with descriptions, enabled in `/dev/`; viewers pick from enabled buckets; no viewer presence. |
| 21 Oct | Spin Azure down when not testing; we run the Azure test ourselves. |
| 21 Oct | Coordinator: fail visibly without a model; prompts stay global; the lab recording upload is removed. |
| 21 Oct | SPADL is the action language across the stack. The backend reads SPADL from ETL via GraphQL. Every stat is redefined on SPADL (126 ids); `shots_saved` counts real goalkeeper saves. |
| 21 Oct | Agents get SPADL definitions in context plus a `lookup_spadl` tool; we optimise for accuracy, not tokens. |
| 21 Oct | Narratives are storylines that develop through the game, grounded in multi-minute trend analysis, not last-minute commentary. |
| 21 Oct | Story subscriptions (see §6) come after storylines and before the final run. |
| 21 Oct | Story follows use Microsoft-Decision-1 (Foundry); one follow per viewer; the pivotal key-moment list is set (§6). |
| 21 Oct | Root Terraform duplicates removed; CI accepts the SQL Server licence; three orphaned backend tables dropped. |
| 22 Oct | The demo always runs exactly three matches from a "Start demo" picker (kickoff, 20′, HT, 60′, 85′); mid-match starts restore seeds recorded on Azure with the winning model, then run live; Cancel demo purges and returns to the picker; the bucket is locked during a demo. Review rounds stop after R17; Azure tests run to half time. Spend: A$15/day budget, alerts only, last-resort guard keeps the viewer up. |
| 22 Oct | Matches are tactically scripted per fixture (press, block height, flank, directness, fatigue, game state) so multi-minute patterns are real; all three re-rendered (Riverton Rovers 1–1 Forgeham, Redcastle Town 1–0 Port Albion, Skybridge 1–1 Whitmore). The old narrative fixtures stay as test-only history. |
| 22 Oct | Spend: budgets email only (A$15/day monthly, and the trial credit); never auto-stop on the daily cap, since judging must not be interrupted. The one automatic action is a last resort at 90 % of the credit that stops Stream Analytics, the feed and SPADL but keeps the viewer and replays up. Stream Analytics runs only while match events flow (`terraform/guard`, runbook §4). |
| 22 Oct | Redcastle Town–Port Albion is the main demo match at full video quality; Riverton Rovers–United and Skybridge–Whitmore upload re-encoded at about 1.75 Mbit/s (`terraform/azure/media.json`); media goes up with azcopy. |
| 22 Oct | The judge build sets `demo_seeds` (DEMO_SEEDS=1 on feed, ETL admin, engine, backend; seeds on an Azure Files share in demo control); `./dev azure up --release` turns it off. |
| 22 Oct | Every live agent on Azure runs on `gpt-6.1-sol` (deployments `writer` for the engine's roles and `questions` for the backend's), replacing the model experiment; Decision-1 stays for claim checks and triggers. Effort `low` everywhere (sol has no `minimal`). Local demos keep the local model. |

## 4. How we review

*In short: rounds of independent agents that read, run and fix, until a round finds nothing.*

- **Each round:**
  - a **system agent** owns the shared local stack (`itg-local`). It rebuilds, starts three matches from kickoff, and follows them with headless viewers, checking stats against each recording's ground truth, narratives, questions, replays, video, purge, restarts and `/dev/` changes.
  - **Area reviewers** read every changed file against the plan, contracts and hackathon rules, and run every test suite in throwaway containers. They fix at the source and report what they found.
- **The brief** every reviewer follows: no commits or checkouts; never print secrets; no provider names; only the system agent touches the shared stack; at most two heavy jobs at once.
- **Done** means a round comes back CLEAN, then the full test on Azure (the developer dropped the separate 90-minute local run on 22 Oct; review rounds already run live matches).

| Round | Main findings (all fixed unless noted) |
| --- | --- |
| Full-match 1 | Data freezes on video lag; ETL slowed to 700 events behind; 40-minute insight cap; lab took over sessions; compound questions refused |
| Full-match 2 | Publisher lag under load; missing full-time insight; model id in history; video stuck behind live |
| 1 | Spoiler leak during stalls; feed purge leftovers; engine fallbacks; migration that would drop Azure connections |
| 2 | Azure parity gap in Stream Analytics; prices, audiences, locks, gaps, profiles |
| 3 | Gap recovery timing; template edits not reaching viewers; feed jam after stalls; DAB config not reloading |
| 4 | Engine `team` layer hard-coded; Azure admin routes public; pre-kickoff links; leaderboards; Event Hubs restart |
| 5 | Security gating in nginx; ETL lost events after hub reset (wrong score); slow inserts; viewer stuck offline |
| 6 | VAR in goals; save qualifiers; statsAtSeq 3× faster; offside crediting in exports |
| 7 | First live SPADL run passed; DAB schema reload; real-saves stat |
| 8 | Saves on the second answer path; block/save wording in the engine; history supersession; budget date |
| 9 | MA3 reads bounded in SQL (`rawEvents.eventSeq`); engine reads bounded by watermark; undeclared capabilities = unknown; test doubles out of runtime; Azure setup order, DAB introspection off |
| 10 | Key-moment wording; engine env quoting caused "model not found"; nicknames from MA1 `knownNames`; docs drift |
| 11 | Result-word phrase list → Decision-1 claim; analyst limits from policy (v3); no cross-viewer text in decision requests; literals to config; `knownNames` in ETL `matchTeams` |
| 12 | Live-check findings (22 Oct): trend patterns and recalibration from the v2 recordings as ETL config (flanks, fade, game state; pressure spells only with territory; fouls no longer notable every match); City–Whitmore 47′ goal is a Esteller own goal and the 22′ "penalty" a free kick (the referee's restart decides); follows get a wrap-up at half and full time (`period_end_wrap_up`); analyst outcomes and comparisons checked by Decision-1 (`claims.*.analyst`, new `comparison` claim); resolved storylines take no analyst moves; labels in plain words (served `meaning`, analyst v4); rarity-weighted follow-chat names |
| 14 | Code-only fixes (22 Oct): storyline prompt limits to policy (`beats_shown`, `resolved_shown_minutes`, `author_match_indicators`; backend 031) and follow-chat `max_candidates`; storylines keep `salienceHistory`, so follow suggestions use salience as of the viewer's clock; writing-model drafts reused when a work item retries after a Decision-1 outage; trend formula constants to ETL `trendParameters` (015, values unchanged); headless check reports protocol errors per page |
| 15 | Code-only fixes (22 Oct): a follower's "story so far" dropped as ungrounded is queued again at later horizons (`subscriptions.catch_up.retries`, backend 032); claim evidence now holds every factual input the writer saw (statistics, recaps, latest events added), so comparisons read off the stats are checked against them; analyst labels face the claim checks and the intent claim is marked `analyst` (032, unedited claims only); Enter sends a question in the viewer (Shift+Enter: new line) |
| 16 | Reviews + live run to half time (22 Oct): comparison claim reads beats and lower-is-more indicators (033); half-time scores are not results (034); pronoun context in claim checks; trim only failing sentences (`repair.author_trim`, 035); `trendParameters` guard (016); feed send tunables (`FEED_SEND_*`); etl-stream drops non-string matchIds; storyline status as of the viewer |
| 17 | Last round (22 Oct): backend SPADL wedge root cause — a rebuild after a failed event write raced an in-flight SPADL read and marked actions counted that the rebuild had dropped (`_loaded` generation, test); ledger lines give the score after each goal and a `score` claim checks labels and excerpts against it; a resolved storyline of the same label reopens within `storylines.reopen_within` (036, served `resolutions`, viewer status as of then); stat table carries the catalogue's definitions, and box vs final-third entry definitions say they are not nested (ETL 017). Suites: engine 174, backend 570, ETL 94 (SQL Server), frontend 154, data-generation 126. Live (2 matches to ~16′ after the host restart): no errors, no SPADL wedge, engine level with the clock, the follower's catch-up written on its retry, key events (Riverton Rovers 9′ penalty and goal) reached the follower; excerpts 3 dropped and 2 trimmed of ~15 (comparison 3, cause 2, all sampled ones genuinely unsupported). Replay benchmark not run (model-bound). Then: a trimmed excerpt is checked again as a whole, so a kept "they" sentence is judged with its new neighbour (test; engine 175); migration 032 cannot override a real edit (a store at 030's seed is the seeded state, and on a fresh store 032 runs before any /dev/ edit), so that limit is closed. |

## 5. Storylines (next build)

*In short: deterministic trends, an analyst that names grounded patterns, and storylines the author develops.*

- **Trend indicators (ETL, exact at any snapshot):** possession, field tilt, attacking-half and final-third share, territory and pressure spells, pressing (PPDA), defensive action height, entries, shots and box shots, fouls/cards/contests, aggression, dominance, momentum, fast breaks. Windows: last 5, last 15, half, match, with change flags. Thresholds live in a `trendDefinitions` table. SQL and a Python reference stay in parity; DAB serves them; Azure parity with no Stream Analytics change. **Built 21–22 Oct:** migrations `011`–`014` (014: flanks, late fade, game state, `direction`/`requires`/`meaning`, recalibrated seed), `reference/trends.py`, DAB entities, parity tests on SQL Server ([trends](etl/docs/components/trends.md)); served live on the shared stack.
- **Analyst (every 5 min, shared, neutral):** the model reads the trends and finds patterns in its own words; nothing is hard-coded. Each pattern must cite the numbers behind it, and a validator only checks that those numbers are real and correct.
- **Storylines:** threads that open, develop and resolve, stored per match (purged with it). The author (prompt v6) advances the focus storyline in each enabled bucket's own framing.
- **Honesty check (done 21 Oct):** on our three recordings, minute-to-minute play behaves like independent draws.
  - Spells, momentum swings, pressing (PPDA), fast breaks, contests and aggression, and the score-dependent patterns are indistinguishable from shuffled data.
  - Half- and match-level control is real and distinct between teams: possession, field tilt, attacking-half and final-third share, defensive height, box entries, dominance.
  - One genuine shift shows at 15-minute scale: Riverton Rovers' field tilt rises from 0.58 to 0.78 after United's red card.
  - Decision: build every indicator and pattern with thresholds in `trendDefinitions`, but seed the unsupported ones `enabled = false` for GRF data. Storylines come from half/match control plus key events.

- **Status (21 Oct):**
  - ETL trends, the analyst, storylines and author v5 are built and unit-tested; backlog equals live over a full match.
  - In a live-model sample, 61% of analyst observations passed grounding.
  - Author narratives are number- and name-checked; causal and intent claims are bounded Decision-1 questions with policy thresholds (22 Oct), replacing a phrase list.

## 6. Story subscriptions (after storylines)

*In short: viewers follow stories; decision models decide when a story moves; only followers get it.*

- **Where:** a chat in the Insights tab lets a viewer follow stories, with suggestions. A follow becomes a formal subscription.
- **Inputs:** the same as the author at narrative time: recaps, recent insights, patterns/storylines and current stats.
- **Triggering:** decision models (bounded classifiers in the Jev/Clef style: typed questions → choice, score or yes/no) check each minute recap, key event and storyline update. A rule-based prefilter runs first, then one batched check per match per update.
- **Feed:** followers see their followed stories, framed in their bucket, and not the generic insights. "Stop following" restores the generic insights.
- **Key moments for everyone:** short, centred, greyed lines for pivotal moments only, e.g. "Goal · Riverton Rovers", "Red card · Harry Kane".
- **Decision model:** Microsoft-Decision-1 on Azure AI Foundry (SystemOne API: typed questions → probabilities). A dev deployment exists, key in the ignored `.local/decision.env`. A constrained-LLM classifier is the fallback behind the same adapter.
- **Over-firing:** for the demo, users can follow almost anything. The chat only clarifies what it can't resolve. A light guard (minimum gap plus novelty check, permissive config defaults) stops spam.
- **Limits:** one follow per viewer, per match. Identical follows share generation; delivery is per viewer. Late followers get "the story so far".
- **Pivotal key moments:** goals (with scorer), red cards and second yellows, penalties, VAR overturns, kick-off/half-time/full-time.
- **Build:** after storylines. The streams are contract, decision adapters, engine trigger pipeline, backend follows and feed, frontend chat and feed, integration. About 3 calendar days in parallel.
- **Status (22 Oct):** contract (F0: [local §8b](local/contracts.md#8b-story-follows), [engine](narrative-engine/contracts/README.md#subscription-targets)), decision adapters (F1: `narrative_engine/decisions/`) and backend (F3: migrations `024`, `027`, follows, feed rules, key moments, follow chat, targets API) are built and unit-tested. Frontend (F4: Insights follow chat, story feed, key moments) is built, unit-tested and headless-checked against the contract mock. Engine trigger pipeline (F2: [follows](narrative-engine/docs/components/follows.md)) is built and unit-tested (live = backlog, restart never re-asks), with a live Decision-1 smoke. Decision-1 limits requests per minute (dev 10), not questions (160 per call verified), so calls are batched and paced. Next: integration on the shared stack (F5).

## 7. Timeline

*In short: estimates, Brisbane time.*

| When | What |
| --- | --- |
| 21–22 Oct | Round 9; storylines experiment; subscription design |
| 22–23 Oct | Storylines build (trends, analyst, storylines, author v5) |
| 23–24 Oct | Story subscriptions |
| 22 Oct | R17 done; Azure test and model experiment; D1 Start demo |
| 23 Oct | D2 seeds recorded on Azure; D3 moment clips and transitions |
| 24 Oct | D4 slow motion; Azure demo acceptance (§10.4) |
| 25–26 Oct | Fixes; judge build left up (§10.5); video |
| 27 Oct | Submission (11:59 pm PT); build stays up until judging ends 11 Nov 5:59 pm AEST |

## 8. Needs the developer

- Confirm hackathon registration.
- Demo video under 2 minutes, the separate project pitch and the description; check every Innovation Studio submission requirement.
- Make the repo public; choose a licence.
- Foundry quota in Australia East (`gpt-6.1-sol` GlobalStandard 250K TPM: `writer` 120K + `questions` 130K; `Microsoft-Decision-1` DataZoneStandard 50 RPM).
- Elephant League branding and real names carried rights risk; the demo now uses the fictional Elephant League (§12 M6).
- Whether to clean old provider names from git history.
- Create the `BUNDLE_DENYLIST` CI secret.

## 9. Known limits

- On the shared local model, three concurrent matches put narratives minutes behind; Azure capacity or fewer enabled buckets fixes it.
- Momentum and fast breaks stay off as claims (too few shots per GRF match to test them); pressure spells are a weak signal, served only alongside territory.
- The Azure Stream Analytics query and the purge and SPADL apps have not yet run in the cloud.
- Decision-1's dev deployment allows 10 requests a minute, so three matches with rewrites lag locally; Azure's deployment is 50 a minute (`DECISION_REQUESTS_PER_MINUTE` from its capacity), and each request batches every claim of a step (`DECISION_MAX_QUESTIONS`).
- After a hard host restart the local Cosmos emulator can keep a stale `postmaster.pid` and never become ready; remove it inside the container and restart that container. (An entrypoint wrapper that clears it at container start is the fix; not applied, because its test needs a removal the developer has to approve.)

## 10. Demo build

*In short: what judges see, the targets each part must hit, and how we prove it on Azure before submission.*

### 10.1 Goals

- A judge opens the URL, presses **Start demo**, picks a start point and within seconds watches three live matches with a rich story so far.
- Everything they see is generated by the deployed pipeline (Foundry models, Decision-1 checks), with no future data and honest labels.
- The build idles cheaply for 16 days and never runs out of credit before judging ends.

### 10.2 Features and order

| Phase | Feature | Done when |
| --- | --- | --- |
| D1 | **Start demo**: always exactly three matches (redcastle-portalbion the main game: starts first, opens by default; riverton-forgeham, skybridge-whitmore); start-point picker (kickoff, 20′, HT, 60′, 85′, DB config); joins a live demo instead of starting another; server refuses a 4th run, single creation under concurrent clicks; **Cancel demo** purges and returns to the picker; bucket locked in a demo; no stop button (runs end at FT); **start progress**: the seven-stage pipeline (Feed → Event Hubs → ETL → Service Bus → Narrative engine → Backend → Viewer, dashed "video · HLS" line) after Start demo and on a cold load of a live demo, each node lit by a real readiness check, with a caption, fading out when all are ready, reduced motion respected | Unit tests plus a local run: two parallel clicks make one demo; cancel leaves no rows in any store; on Azure from zero, every node lights in order only when its check passes and the viewer opens within 30 s |
| D2 | **Seeds**: one full run per match on Azure with the winning model; every store snapshotted at each start point (ETL, engine storylines and narratives, follows, insights); restore through each owner's admin API, then the feed continues live; label "story so far generated earlier on this pipeline; live from N′" | Restored state equals the recorded run at that seq; nothing past the start point readable; insights read as if watched from kickoff |
| D3 | **Moment clips in follows**: when Decision-1 judges a moment highly relevant to a follow and it is countable and rare (goal, penalty, red card, VAR), its clip joins that follow's single playlist in Insights next to the follow narrative; no separate feature to set up | **Built 22 Oct** (code and tests; live check pending): engine asks a clip `Score` on key events of `subscriptions.clips.key_types` in the same Decision-1 call (a clip moment bypasses the gap guard); a `clip` verdict sends its own `FollowClip` message, apart from the follow narrative, so a narrative dropped as ungrounded keeps its clip; the backend adds it to `subscription_clips` (migrations 038, 039); the snapshot carries `follow_playlist`, cut with replay-timing on the match stream, newest kept, bounded to the viewer's seq; Insights pins it as one replay card. Tests: engine 181, backend 578, frontend 168. Live: a team follower gets each of their team's goals as one playlist; common events (passes, fouls) never clip |
| D3 | **Clip transitions**: hold the clip's last frame, fade a sting in, cut under it, fade it out as the next clip plays; every reel (replies and follow playlists) | **Built 22 Oct** (code and tests; live check pending): sting is the community GIF the developer chose (Elephant League resources permitted for the hackathon; provenance in `frontend/assets/league/PROVENANCE.md`), converted to a 0.66 MB MP4 (SSIM 0.997, frames unedited); settings in `replay-timing.playback.transitions` (migration 037, `/dev/`): `enabled`, `hold_seconds` 0.6, `asset`, `asset_start_seconds` 0.3 (starts on the white burst), `sting_seconds` 2.4, `cut_seconds` 0.5, `fade_seconds` 0.3; served with every replay as `playback`; `prefers-reduced-motion` holds and cuts with no sting. Tests: frontend 167 (reel state machine: hold → sting → cut → play, skip, seek, reduced motion; stage timers), backend 573 (migration 037 keeps edits; replays carry `playback`); headless `--flow sting` ok at 1440/390/360 px; 16-frame capture over a held match frame reviewed |
| D4 | **Slow motion** into and out of the key moment | **Built 22 Oct** (code and tests; live check pending): playback rate eases to `rate` 0.5 over `ramp_seconds` 0.6, holds from `before_seconds` 1.0 ahead of each marked event to `after_seconds` 1.5 past it, eases back; `replay-timing.playback.slow_motion` with `enabled`; off under reduced motion. Tests: `slowRate` and stage rate. Live: visible slow-down at the event in replays and moment clips |
| D5 | **Cross-game** (built 22 Oct, unit- and API-tested; not yet live-checked): from any demo match, ask about, pin from and follow another live match. Follows stay opt-in through the existing follow UX: **Customise** opens the follow view, whose chat replaces Insights (short instructions, Cancel always there); "follow City's pressing" or "Whitmore' defence" resolves in another match from the same chat (no separate cross-game UI); once following, that story's narratives (the "storyline window") show there, yellow-outlined with a small header (both teams' names and crests, no score). Answers, pinned stats and replays from another match get the same marking. Each match is read at its own played position. Reusable: `user-backend/backend/services/cross_match.py` (`CrossMatch.named`, `.other`, `header`), `frontend/match/other-match.ts` (`otherMatchHeader`, `markOtherMatch`); contract local/contracts.md §8c; config `cross-match` (migration 040) | Live: a viewer on Redcastle Town–Port Albion follows City; City narratives arrive yellow-outlined with the City–Whitmore header; nothing past City's own played position; no shared narrative names another match's teams |
| D5b | **Follow this story?** (built 22 Oct, unit-tested): a question-chat answer that is not a stat gets one yes/no decision (Microsoft-Decision-1, else the local model; question, threshold, pacing and timeout in config `follow-offer`); if yes the answer card offers Follow / No thanks. Follow opens the follow view and sends the question to the follow chat, which proposes the story (this match or another); the viewer confirms; never an automatic follow; one offer per answer | Live: "How is Ellingham getting on?" offers a follow; "How many shots?" never does; accepting proposes Ellingham in the follow view |
| D6 | **Capture**: clips served inside the **follow view** (Customise or the chat opens it; it replaces Insights while the viewer follows; Cancel or Stop following returns to Insights), beside the followed storyline's narratives, for this game or another; each clip plays with slow motion and the sting; Decision-1 decides clip-worthiness on the same batched follow path, or a topic kind is clip-on from creation; clip kinds and thresholds in DB config | **Built 22 Oct** (code and tests; live check pending): the D3 pinned playlist became one feed card per clip at its moment's clock in the follow view (`frontend/match/capture.ts`); Play opens the follow playlist from that clip on (sting and slow motion from `playback`); another match's clips carry its header (D5 `other-match.ts`). Clip-on: `subscriptions.clips.always_for` (topic kinds, default none; migration 041) skips the clip `Score` and clips every clip moment the topic is a candidate for (engine `follows/pipeline.clip_on`). Tests: engine `test_a_clip_on_topic_clips_without_the_clip_question`; frontend follow feed tests. Live: following a team, each of its goals arrives as a captured clip within a minute of the event, in the follow view |
| D6 | **Clip preview cards**: a generated preview per clip: league-style gradient, the minute and simple event name, plus scorer/player and the score after | **Built 22 Oct** (headless-checked against the mock): rendered in the browser (HTML/CSS, not SVG/canvas, so the feed's DOM tests cover it) from each clip's `moments` (backend `follow_clips.CARD_FIELDS`; `feed_moments` now also serves `team_name`, `player_name`, `score`): club-colour → league-purple gradient, crest, minute, event (first part of the configured label), player or team, score after; a reply's replay card shows the minute and event line when its first clip is a key moment. `headless-check.ts --flow capture` passes at 1440/390/360 px in Insights and the follow view. Live: every captured clip and key-moment replay shows its card |
| D7 | **Key-event clips in shared narratives**: when a key event triggers the shared (non-follow) engine step, its clip is generated and served with that narrative to every viewer of the bucket, in normal Insights | **Built 22 Oct** (code and tests; live check pending): the engine sends a `MomentClip` (buckets of the step) before the key-event step's narratives when `subscriptions.clips.enabled` and `.shared` (migration 041, default on) and its type is in `clips.key_types` (`core/orchestrator._publish_moment_clip`); the backend keeps it per (bucket, moment) in `narrative_clips` (purged; seeded in `backend/demo/seeds.py`), serves `moment_playlist` to that bucket's Insights viewers, bounded by `event_seq`; the feed shows it as a capture card. Tests: engine `test_each_clipped_key_event_sends_one_moment_clip_for_the_shared_narratives`; backend `test_key_event_clips_reach_every_insights_viewer_of_their_bucket`, `test_a_key_event_clip_never_passes_the_snapshot`, `test_capture_clip_settings_reach_existing_stores_and_keep_edits`. Live: a goal's shared narrative arrives with its clip and preview card |
| Review | **Developer review fixes (22 Oct)**: insights about half as long (narrative-author: one or two short sentences, at most the one or two decisive numbers; live as /dev/ version 9, seed via migration 042); feed oldest first, newest at the bottom with auto-scroll; Customise at the bottom; chips and phone stat cards wrap (no sideways scroll); shorter copy; keyboard-only focus rings; follow planner v2 keeps the viewer's focus in labels and clarifies with up to four drill-in options resolved by code (unknown ones dropped); "Following since N′" marker; stats row bottom aligned with the companion; question agent and planner get the live matches (teams, minute) as context, a request about several other matches gets only the real matches as chips, footnote "Answers grounded in live matches" | Tests: backend 601 (Postgres), engine 186, frontend 176; headless follow flow at 1440/390/360 px against the mock |

### 10.3 Targets

| Area | Target |
| --- | --- |
| Start | Picker to first frame and story so far within 10 s (seeded starts); kickoff start shows the first narrative by 2′ |
| Lag | Engine narratives at most 2 match minutes behind on three concurrent matches (winning model on Azure) |
| Grounding | Excerpts dropped or trimmed under 15%; no wrong-direction comparison or wrong score accepted (sampled) |
| Follows | Catch-up within one minute of following; HT and FT wrap-ups reach every follower |
| Isolation | No text names another match's teams; no read past a viewer's seq |
| Cost | Idle A$3/day or less (scale to zero, paused DB, Stream Analytics only while a match is live); one judge session (three matches to HT) A$2 or less; total through 11 Nov within the remaining credit (US$197, expires 17 Nov) |
| Availability | URL works from a fresh browser on an unknown IP, no login; cold start under 30 s |

### 10.4 Azure demo acceptance (before submission)

1. `./dev azure up` from clean; spend budget and guard in place.
2. Seeds recorded (D2) with the winning model.
3. From a fresh browser: Start demo at each start point, plus kickoff; Cancel demo between them.
4. Check every §10.3 target and the D1–D4 "done when" column; screenshot each.
5. Leave idle for 12 h; confirm idle cost and that the next Start demo cold-starts within target.
6. Record results here; fix and repeat any failed row.
7. Docs and diagrams cover D1–D7: root and service READMEs, `docs/` component pages, contracts, and the architecture/development SVGs regenerated (`.github/scripts/render_*.py`) and visually inspected.

### 10.5 Judge build

Stays up from submission until judging ends (11 Nov, 5:59 pm AEST): free, no IP allow-list, no login. Budget alerts by email only; the last-resort guard (forecast exhausts credit before 11 Nov) stops Stream Analytics and scales non-serving parts down while the viewer stays up. `./dev azure down` after 11 Nov.

### 10.6 D1 as built (22 Oct) and the seed design (D2)

D1, tested in unit tests (feed 24 + Postgres 4, demo control 7, frontend 6); not yet run on the stack:

- **Feed** (`data-generation/feed`, migration `002_demo.sql`): `demo_settings` holds the fixtures, stagger (120 s), the cap on scheduled or live runs (3) and the start points (match clock: kickoff, 20′, second half, 60′, 85′; each fixture maps a point to its own video second). `POST /demo/start {point}` starts the fixtures once (concurrent clicks: one demo; while one is on it returns its runs) and purges the feed's finished runs first; `POST /runs` past the cap is `409`, so `/dev/` manual starts obey it too; `GET`/`PUT /demo` (revision-checked) edit the settings from `/dev/`.
- **Demo control** (`local/demo_control.py serve`, Compose `demo-control`): the operator between provider and our services, not a product service. `POST /start` purges finished matches from ETL, engine and backend, then asks the feed to start; `POST /cancel` purges every match (`all`, finished staggered runs too) from every owner, feed first; start and cancel never interleave (one lock, so one replica). `GET /state` lists start points (`ready` only when recorded) and whether a demo is on. nginx exposes only these four (with `/status`) at public `/demo-api/` (no login): start and cancel POST only, one shared limit for every viewer (10/min, burst 5); state and status GET only, per client key (40/s, burst 200: behind the edge a whole city shares one key); over the limit is `429`.
- **Main game** (22 Oct, feed migration `005_demo_main.sql`): `demo_settings.main_fixture` (default `redcastle-portalbion`, editable in `/dev/`) starts first, so it is always furthest along, and leads the fixture list; `/demo-api/state` names its run (`main_match_id`). After Start demo, or on landing on `/` while a demo is live, the viewer opens the main game; "← All matches" (`/?choose`) keeps the picker, main game first, for switching to the other two. Tests: feed 31 + Postgres, demo control 10, frontend 169.
- **Start progress**: demo control `GET /status` (public `/demo-api/status`) reports each stage from a real check, which also wakes apps scaled to zero: feed `/health`; Event Hubs = a demo run's MA1 accepted by the hub (feed run `position` ≥ 1; staggered runs send theirs minutes later); ETL `/health`; Service Bus = ETL and engine both up (no separate probe yet); engine `/health`; backend `/health`; viewer = the backend lists every demo match whose MA1 has gone out. It lives in demo control, not the backend, so no product service learns about the others. Seed-restore progress joins it with D2.
- **Viewer**: picker shows Start demo with the start-point select (unrecorded points disabled), or Cancel demo while one is on; while a demo is on only its matches are listed. The audience bucket is fixed while a match is live.
- **Azure (built, §11)**: a `demo-control` Container App (`terraform/demo_control.tf`: internal ingress, one replica; ETL and engine admin tokens; `DEMO_FEED_URL`, `ETL_ADMIN_URL`, `ENGINE_ADMIN_URL`, `BACKEND_URL`) and `DEMO_CONTROL_UPSTREAM` on the frontend. Without it `/demo-api/` returns 502 and the viewer hides the controls.
- **Open**: one viewer's Cancel stops the demo for every viewer (as asked); a confirm dialog guards it.

**Seeds (D2, built 22 Oct; tested in unit tests and on the local stack).** A seed is recorded, not reconstructed:
`demo_control.py record {point} [--from {point}]` starts one *held* run per demo fixture (feed `POST /runs {hold_point}`:
the run sends nothing at or past the point's video second, HLS included), from kick-off or from an earlier seed;
`demo_control.py capture {point}` waits until every owner has settled on what the run sent (ETL watermark = the
run's seq, the engine has summarised the last minute with nothing queued, the backend holds every event and every
engine narrative), exports each owner's rows and names the seed on the feed's start point. So nothing past the
point exists in a seed by construction, and HT, 60′ and 85′ are recorded as a chain (each from the previous seed).
Locally seeds live in `.local/seeds/{seed_id}/` (mounted into demo control as `/seeds`); on Azure the same
layout on an Azure Files share mounted at `/seeds` (`terraform/demo_control.tf`). Layout: `manifest.json` (format 2, seed id, point, created_at,
each owner's schema fingerprint, per fixture the source match and run ids, seq and video second) and
`{owner}/{fixture}.json`. A seed of another format, or that an owner's schema no longer fits, is refused (`409`:
record it again), as is one whose seq differs from where the feed resumes:

| Owner | Export / restore | Holds |
| --- | --- | --- |
| feed | none | the run resumes at the point (`resume_point`), position and seq taken as delivered, no MA1 |
| ETL | `GET /admin/matches/export?match_id=` / `POST /admin/matches/restore {match_id, max_seq, schema, tables}` | every match table (events, SPADL, trends inputs, progress, windows); the worker reloads its state from SQL |
| engine | `POST /admin/matches/export` / `POST /admin/matches/restore {match_id, max_seq, schema, containers}` | checkpoint (follow state cleared), context blocks, narratives, analyses, storylines; viewers' follow decisions and narratives are not seeded |
| backend | `POST /admin/matches/export` / `POST /admin/matches/restore {match_id, max_seq, schema, tables}` | received match and events, gaps, audience catalogue, engine narratives (the insights history) and their key-event clips (`narrative_clips`); sessions, follows, questions and calculations belong to viewers |

**Demo-only adapter (DEMO_SEEDS).** Seeding lives in one demo adapter per service, mounted only when `DEMO_SEEDS=1`: backend `backend/demo/seeds.py` (router added in `app.py`), engine `narrative_engine/demo/seeds.py` (an ASGI layer in front of the service app), ETL `local_stream/demo_seeds.py` (routes handed to the admin server), and in the feed (the provider simulator) the held/resumed runs, seeded `/demo/start` points and `POST /runs/{id}/release`. Without it a service has no export or restore route and the feed refuses seed recording (403) and seeded starts (409). Restore tricks the system through its normal shapes: it writes rows and documents as the live pipeline writes them, then the owner adopts the match the way it recovers after a restart (backend `MatchRegistry.adopt`, ETL worker `load`, engine `Router.engine`); core services never branch on a demo. Local compose and the Azure judge build set `DEMO_SEEDS=1`; a production release leaves it unset. Tests: each service proves the routes are absent without it (backend `test_seed_routes_exist_only_with_the_demo_setting`, engine `test_without_the_demo_setting_the_service_has_no_seed_routes`, ETL `test_seed_routes_are_mounted_only_with_the_demo_setting`, feed `test_without_demo_seeds_there_is_no_seed_path`) and the seed round trips pass unchanged with it on.

**Restore and continue.** `POST /demo-api/start {point}` with a seeded point: the feed creates the three runs
*waiting* (`awaiting_restore`; not launched, nothing sent); demo control rewrites each fixture's seed to the new
matchId and runId (and its MA1 time to now, so later purge-all cut-offs do not drop it), restores ETL alongside the
backend, then the engine (which asks the backend for the match's targets; each refuses another schema, a known or tombstoned match, rows of another match, and rows
past the seed's seq), then releases the runs (`POST /runs/{id}/release`), main game first, staggered: each clock
starts at the point 5 s later, plus the stagger. Any failure purges the runs everywhere (`503`; a stale seed `409`). Start and cancel answer `202` at once and run in demo control; `/state` reports `pending` and the `last` outcome, which the viewer polls. Every restored document is bounded by the seed's seq: ETL canonical, MA3, SPADL (`seq`, `finalSeq`), possession and progress rows by seq, key events by their MA3 row, minute stats by the last event; the engine's narratives, analyses and queued steps by seq, storylines by their analyses, summaries by the checkpoint's closed minute. Restored ETL rows count as ingested now, so a seed older than a day still reloads its open minute window.
While a seed is being recorded its held runs are no demo: `state` leaves them out and `start` answers `409`. Each run carries `started_from`; `/demo-api/state` returns
`live_from` and the viewer says "The story so far was generated earlier on this pipeline; live from N′." A viewer
who follows a story at a seeded start gets the usual catch-up ("story so far") step.

Tests: feed (held run stops at its point; a seeded demo waits for release, then resumes without MA1 or earlier
events; a demo failing part-way leaves no runs), demo control (restore order, id and MA1 rewrite, staggered
release, purge on a failed restore, the settle check), ETL (a restored seed fed only what follows writes the same
rows as one uninterrupted run), engine (export → purge-all → restore under a new id → nothing redone, later minutes
continue), backend (export, refusals, restore, the match tracked again).


### 10.7 Local integration check (22 Oct, evening)

*In short: D1–D7 checked end to end on itg-local with all four seeds re-recorded on the final build; local model throughout.*

- **Build:** `./dev up backend` passed (594 backend tests, every broker probe); backend migrations to 042, feed to 005. Old seeds (no format) are refused with a clear 409 and now show as not ready; 20′, HT, 60′ and 85′ were re-recorded on this build (`.local/seeds/*-20261022T09…/10…`).
- **D1:** two concurrent seeded Start demo calls made one demo of three runs; the progress screen lit each stage, then opened the main game (Redcastle Town–Port Albion); Cancel purged every owner; bucket locked while live. Fixed: the viewer jumped to the main game before the progress screen finished, the "live from N′" note was only on the picker (now also in the match view), and a picker crash (`COLD_START_MS` used before its declaration).
- **D2:** seeded starts show insights from 5′ onwards as if watched; nothing past the start point. Start time 11 s at 20′ but 51 s at 60′ (larger seeds restore slower): **misses the 10 s target**.
- **D3/D4:** clip plays with slow motion (0.5× ramped back to 1×) and holds at the end; multi-clip sting covered by the headless check, not seen live.
- **D5:** cross-match question (yellow outline, Redcastle Town v Port Albion header, its own 5′), cross-match pin and cross-match follow all work. Fixed: the follow chat took the first other match a shared word matched ("Skybridge City" followed in Riverton Rovers–United); it now keeps the best-fitting match.
- **D5b:** Decision-1 scores story questions (0.87) above stat-like ones (0.15). Changed: an unanswered story question now also gets the offer (never a clarification or stat). The local question model often answers story questions as stats or clarifications, so the offer was not seen live.
- **D6:** a Whitmore follower got Palmeira's second yellow as a captured card (77′, Skybridge 1–1 Whitmore) in the follow view. Fixed: Decision-1 returns the expected level, so a clip needing the top level almost never fired (2.74 for a team's own goal); the clip now counts at its nearest level.
- **D7:** key-event clips stored for every bucket (penalty, goals, own goal) and shown in Insights.
- **UX:** newest insight at the bottom, Customise at the bottom, no horizontal scroll, `:focus-visible` rings, stats and panel aligned, "Following since 62′"; "what other games are on" answers with both other matches as choices. Drill-in chips did not appear for "Redcastle Town's goals" (it proposed the follow directly).
- **Targets:** engine lag about 2 match minutes on three matches; no shared narrative named another match's teams (scan of all stored narratives); no errors in any service log after the rebuild.
- **Open:** seeded start time at 60′/85′; replay questions on the local model sometimes cite moments without searching ("Replay plan cited no returned evidence"), and one answer failed schema validation; indicator jargon ("field tilt", "PPDA") still appears in some insights.
- **Fixed after the check (code only, 22 Oct; stack not re-run):**
  - **Seeded start:** the engine's restore wrote each Cosmos document in its own round trip; it now uses transactional batches per container (the match's partition), checkpoint last: three 60′ matches 9.0 s → 2.2 s on the emulator. The backend parses and validates a seed off the event loop: three 60′ restores 5.4 s → 3.2 s. ETL (OPENJSON, one transaction per match, emulated SQL Server on this Mac) stays the long pole: 20′ 7.7 s, HT 6.5 s, 60′ 9–11 s, 85′ 16 s for three matches; bulk copy and per-table connections were tried and dropped (pymssql bulk copy mangles nvarchar; no gain). Demo control runs ETL alongside backend then engine, so a seeded start is about the ETL time: within 10 s up to HT, about 10 s at 60′, about 16 s at 85′ locally. Native Azure SQL should be faster; re-measure there.
  - **Replay on a restored match:** the replay agent is shown recent and key events (with their ids) in its input, but only ids returned by its tools counted as evidence, so a plan citing a goal it was shown (common once a seeded match already has key events) was dropped. Shown events, and the events a key moment lists, now count; `action:{id}` is read as the bare id. Tests: `test_replay.py` and `test_multi_match.py::test_a_restored_match_answers_replay_questions`.
  - **Jargon:** the analyst's trend table showed ids (`ppda`, `field_tilt`), which leaked into labels and insights. It now shows each trend's plain label; the validator maps labels back to ids, so evidence is still checked against the served rows. ETL migration 018 relabels `field_tilt` ("share of final-third play") and `def_height` ("defending height"). Test: `test_writers_see_trend_labels_never_ids_and_the_analyst_cites_by_label`.
  - **Suites:** backend 607 (Postgres), engine 185 + 2 skipped, ETL 97 (SQL Server); the backend's prompt-copy test now points at author v7.

### 10.8 Local check on the fictional league (23 Oct)

*In short: every suite passes on HEAD and the full flow works on itg-local with the Azure sol seeds; four fixes.*

- **Suites:** data-generation 108, feed 41 (Postgres + Azurite), ETL 103 (SQL Server 2025) then 23 seed/stream tests after the fix, engine 191, backend 627 (+1) and every broker probe, frontend 198, demo control 28, `./dev terraform check`, `./dev udfs --check`.
- **Fixed:**
  - Feed blob route test double lacked `seeds` (failed since DEMO_SEEDS).
  - Azure seeds were refused locally ("another ETL schema"): the fingerprint covered the stand-in's `localStreamWindows`, which Azure lacks. It is now left out; an Azure seed's closed windows come from its minute stats, so the worker reopens nothing (`test_sql_seeds.py[azure]`, fails without the fix). `demo_control.py adopt {seed_id}` offers a copied seed.
  - /dev/ refused every narrative-author save ("Unknown {match_trends}, {storylines}"): it was given the oldest version's placeholders, not the active one's (`test_prompts.py`).
  - /dev/ audience saves dropped each option's `team` and `in_label` (Standard's `in_label: false`), so one save changed bucket labels (`dev.test.ts`).
- **Flow (anonymous viewer, localhost:18020, local model):** stale pre-league matches purged first. Start demo 20′: ready in 2.8 s, Redcastle Town v Port Albion opened with the story so far, picture at 20:11 about 25 s after Start; three matches listed, main first. First live narratives at 24′ about 6.5 min after Start, one per enabled bucket (home:analytical, away:casual, neutral:simple), author v9; engine lag about 2–2.5 match minutes. "How many shots has Redcastle Town had?" 2, in 10.7 s; "How is the Skybridge City v Whitmore game going?" a marked answer as of 19:59 in 21.3 s. Follow Whitmore (other match) confirmed; catch-up in about 40 s. Skip +10′: picture jumped in about 25 s. The 48′ own goal arrived as a capture card (Skybridge 0–1 Whitmore) with its follow narrative and played as a replay with live picture-in-picture. Cancel: in-page dialog, every owner empty within 5 s. No shared narrative names another match's teams (75 scanned).
- **Live config (/dev/):** disabling away:casual on redcastle-portalbion took its next step to 2 buckets (audience revision 2) while the other matches kept 3. A narrative-author v10 asking for a "Live check:" opening was used by the very next steps of all three matches. Both restored (v9 active; template inherits the default again).
- Left running: a demo seeded from 20′ (started 00:10 UTC, ready in 8.8 s). Host swap 3.8 of 5 GB in use; the stack used 3.7 GiB.

## 11. Azure judge build (22 Oct)

*In short: up at the azurecontainerapps.io URL and msft-hackathon.koda-software.com; all agents on gpt-6.1-sol. Redeployed 23 Oct with the fictional league; all four seeds recorded on sol; a seeded 60′ start takes about 8 s.*

- **Fixed while deploying:**
  - The Stream Analytics query didn't compile: `System.Timestamp()` was used in `HAVING`, so quiet spells became the `QuietSpells` step.
  - Progress marks were dropped as type-conversion errors, so the watermark never moved. The output columns are now cast.
  - Resource-group budgets outlived their groups and blocked `up`; `down` now deletes them.
  - The spend guard's Automation account had to move to East US, because Free Trial blocks Australia East.
  - `azure-setup` now retries while serverless SQL resumes.
  - SQL now bills past the free limit instead of pausing for the rest of the month.
  - Media goes up with azcopy, with the secondary matches re-encoded: 1.1 GB each, about 8.5 min each, against about 45 min before.
  - The picker loads in parallel, times out and retries, and shows start-up progress.
  - Demo control wakes every owner in parallel.
  - The backend sends `reasoning_effort` and no temperature to reasoning models.
  - The backend's follow check uses Decision-1 (`DECISION_*`, key in Key Vault). The adapter takes only a key or a static bearer, so it isn't keyless.
- **Half-time test (gpt-5-mini, 3 matches 2 minutes apart):**
  - Events flow end to end.
  - Steady engine lag is about 0.2–0.5 match minutes (catching up after the query fix peaked at about 15).
  - Half-time wrap-ups reached the follower in all 3 matches.
  - Decision-1 served 279 requests.
  - HLS and the /dev/ gate work, and there were no errors.
- **gpt-6.1-sol (20′ seed recording, 3 matches at once):**
  - Engine lag is about 0.5 minutes.
  - 20 minutes cost about 275K prompt and 17K output tokens on `writer`, roughly US$0.7 at list price before caching. A session of three matches to half time is about US$2 (A$3).
- **Idle estimate:** about A$6–7 a day, with Stream Analytics stopped and SQL paused. Most of it is container apps at the idle rate (A$2.1), the two PostgreSQL B1ms servers (A$1.9), Event Hubs (A$1.1), Service Bus (A$0.5) and the registries (A$0.5).
  - Through 11 Nov that is about A$130, plus about A$3 per judge session, against about A$281 of credit. 40 sessions would leave about A$30.
- **Stopped at (pause, 22 Oct ~11:35 UTC):** the 20′ seed is captured. The HT, 60′ and 85′ chain is not recorded. Seeds are not downloaded to `.local/seeds/`. The guard stream schedule's start/stop isn't yet verified across an idle period.
- **Question fix (22 Oct ~12:00 UTC, backend only):**
  - gpt-6.1-sol takes function tools only over the Responses API. Chat Completions rejects tools with any `reasoning_effort` and doesn't accept `none`. So reasoning models now use the Responses client (`chat_client`, with a `reasoning.effort` option), and chat models keep Chat Completions with temperature 0.
  - Failures now log the exception chain's text.
  - Cross-match questions then hit 429 at 50K TPM, so capacity moved to `writer` 120K and `questions` 130K (az CLI live; Terraform defaults match).
  - Verified on Azure: the Nordahl replay, Redcastle Town shots and "How is the Riverton Rovers game going?" all answer.
  - The backend was rolled by hand (image `v20261022120136`, outside `image-tag.txt`); the next `up` rebuilds everything anyway.
  - The restart replayed Event Hubs into the seed-restored matches (`received_events` duplicate key, `gap` float − None). The matches kept advancing; the code-only agent's restored-match fix covers it.

- **Fictional-league redeploy (23 Oct AEST, 22 Oct 17:00–21:15 UTC):**
  - Built from a clean worktree, never the working tree. Six `./dev azure up` runs (judge build, `DEMO_SEEDS` on): 3c2a163, then 5b2a0f1, df3e328, eb041b2, 62d8298 and 845fa99 as each fix landed. The last image is `v20261023065917`. Edge `UPSTREAM` is unchanged (same FQDN), so there was no Worker deploy.
  - Migrations applied: feed 006–008 (main game `redcastle-portalbion`, old seeds cleared) and backend to 049. The /dev/ Models config (`/dev-api/config/models`, all roles on the service default) and the `length` layer (Standard/Brief) load.
  - Media uploaded: redcastle-portalbion 2780/2780 segments at full quality (31 min); riverton-forgeham 2773 and skybridge-whitmore 2794 from the `-90-low` encodes (8–10 min each). The three new recordings are up. The old real-club media (`arsenal-liverpool`, `chelsea-united`, `mancity-tottenham`: 8,350 blobs), recordings and the stale 20′ seed were removed once the new ones played. That seed is kept in `.local/seeds-pre-league/azure/`.
  - **Fixed: Stream Analytics out of memory.** The job read back a day of hub history on start (`LIMIT DURATION(day, 1)` and one-day sessions), ran at 100 % SU (`StreamingNodeHighMemoryUsage`) and wrote no progress marks. So the watermark stayed at 0 and the engine paused ("MA3 rows past the committed seq 0"). The lookback is now 10 minutes and sessions are capped at 4 hours; afterwards it runs at about 40 % SU with about 25 s watermark delay. Test: `test_azure_parity.py::test_progress_lookback_covers_every_gap_and_sessions_outlast_a_match`.
  - **Seeds on sol (22 Oct UTC):** `20-20261022T184253Z`, `ht-20261022T191222Z`, `60-20261022T193057Z` and `85-20261022T195843Z`, each chained from the previous one. Recorded with no demo running. They are copied to `.local/seeds/`; the old local seeds moved to `.local/seeds-pre-league/`.
  - **Seeded start times through the edge.** Times are Start to `/state` live; the server's "ready" is about 2 s less.
    - 60′ took 11.1 s at first. ETL restore took 6–8 s and the seed read 1.6–2.9 s, both on 0.25 vCPU.
    - Then the ETL admin and demo control moved to 1 vCPU / 2 GiB (both scale to zero), and demo control keeps the offered seeds in memory from the picker's first `/state`. 60′ now takes **8.1 s** (restore 5.2–5.8 s, read 0.4 s); 20′ takes 3.7 s server-side (restore 2.2 s), and the viewer was on the main game by 12.6 s.
    - A cold ETL admin added about 19 s (HT took 25.6 s), so demo control now also wakes every owner when a viewer opens the picker. Test: `test_a_viewer_at_the_picker_wakes_every_owner_at_most_once_a_keep_warm_round`.
  - **Verified as an anonymous viewer** (no login, fresh tab, through msft-hackathon.koda-software.com):
    - All three matches start, with Redcastle Town v Port Albion first; the viewer opens it, its video plays and insights show from the seed.
    - "How many shots has Redcastle Town had?" was answered in 6.4 s. "How is the Skybridge City v Whitmore game going?" got a yellow-outlined answer as of 59:59 with a follow offer.
    - A cross-match follow (Whitmore, then Skybridge City) got its catch-up narrative within about 10 s.
    - A capture card (48′ own goal, Skybridge 0–1 Whitmore) arrived in the follow view and played as Replay 1/2 with the live picture-in-picture.
    - Skip ahead +10′ and +20′ jumped the video and the pipeline caught up within about 2 minutes.
    - Cancel (UI) ended the demo at once; purging every owner took 3 min 19 s for a 60′ demo that had been skipped to 80′ (feed HLS blob deletes 1.5 min, ETL 1.7 min).
  - **Fixed: Skip ahead was invisible.** It, and the "live from N′" note, sat in the toolbar that hides once the connection is live; now only the connection line hides (`match-dom.test.ts`).
  - **Open:**
    - Demo control was cold-starting in about 40 s on a first visit; the developer chose to keep one replica warm (min 1, about A$0.6–1.2/day) through judging (23 Oct).
- **Judge-build fixes (23 Oct, 22 Oct UTC evening):**
  - **Fixed: the follow planner had no score for another match.** The live-match listing (planner and question context) now carries each match's score at its own position: the viewer's snapshot here, ETL's watermarks there (`CrossMatch.listing`). Reproduced on Azure first ("I don't have the score available"). Tests: `test_cross_match.py::test_another_match_stands_where_etl_has_it_with_stoppage_minutes_and_its_score`, `::test_the_follow_planner_is_told_each_live_matchs_score_and_minute`.
  - **Fixed: a goal against a followed team fired nothing.** Reproduced on Azure: a Whitmore follow, Skybridge's 69′ equaliser scored 1.95 with confidence 0.17 (trigger level 2, min confidence 0.3), while the 48′ own goal only just passed (2.46, 0.37). The ledger already had the score; the update did not, and "the team Whitmore Wanderers" left Decision-1 unsure what the story was. Replayed against Decision-1: with the score before and after in the update and the subject as "everything about the team …" (the planner's own definition), the same equaliser scored 2.03–2.1 with confidence 0.67–0.77, while a quiet minute stayed at 1.1 (0.8). The fire rule now also uses the nearest level, like the clip score. No goal rule and no prompt wording added. Test: `test_follows.py::test_a_goal_reaches_the_decision_with_the_score_before_and_after_it`.
  - **Fixed: "Demo footage unavailable" after a seeded start.** The viewer shows "Starting the stream…" and retries every `STREAM_RETRY_MS` until the first segment plays; unavailable only without a stream, or after `STREAM_START_WAIT_MS` (45 s) live (`match/video.ts`, `video.test.ts`).
  - **Fixed: Cancel used a native `confirm()`.** Now an in-page dialog; Escape or Keep watching keeps the demo (`demo.test.ts`).
  - **Stream Analytics restart lag: mostly Azure's.** The activity log shows the job's own start takes 75–90 s, and the traffic alert adds 1–3 min (metric ingestion) plus the runbook start before it is even asked. Ours: a demo Start now calls the guard's stream-start webhook at once (`DEMO_STREAM_START_URL`, a Terraform secret from `terraform/guard`), so only the job's own start remains. The viewer's clock stays on ETL's watermark on purpose: a feed-driven clock would run ahead of the score and stats it shows. Every `./dev azure up` also restarts the job (query changes), so a demo live during a deploy shows the lag. Test: `test_demo_control.py::test_start_asks_the_guard_to_start_stream_analytics_at_once_when_configured`.
  - **Deployed** 2faaea4 with `./dev azure up --yes` (judge build, image `v20261023074325`; the working tree was clean at that commit; edge `UPSTREAM` unchanged). **Verified as an anonymous viewer** through msft-hackathon.koda-software.com: Cancel demo asks in the page ("Cancel the demo?", Keep watching / Cancel demo) and cancelled; Start demo from 20′ opened Redcastle Town v Port Albion with "Starting the stream…" and the picture within about 20 s, never "unavailable"; the follow chat answered "follow Whitmore in the other game, what's the score there?" with "Their game against Skybridge City is 0–0 at 20′" and a Follow card. Demo control logged "Stream start requested: HTTP 202" at Start.
  - **Verified live (equaliser follow):** an anonymous viewer of the main game followed Whitmore Wanderers in Skybridge City v Whitmore through the edge at 56′. Skybridge's 69′ equaliser (`key:1999`) now scored 2.03 with confidence 0.65 (was 1.95 / 0.17) and fired. The follow narrative ("Whitmore's lead has gone: … makes it 1-1 at 70′ …") reached that viewer's session, after the catch-up and a 56′ update.
  - Left running: a demo seeded from 20′ (started 21:54 UTC).

## 12. Team review actions (22 Oct meeting)

*In short: everything the team asked for after using the Azure demo; each row closes only with evidence. Decided: the simulated matches stay as they are (aggressive, weak keepers); the data is swappable, so the generator is not tuned further. Each finished batch of M-items is committed and pushed to `main` so a teammate can review and run it.*

| # | Action | Owner area | Status |
| --- | --- | --- | --- |
| M1 | Two people in different browsers must be two viewers (they were treated as one session, so questions and prompts crossed over) | frontend/backend sessions | **fixed in code**: conversations were keyed by (demo profile, match), so every browser on one profile shared a conversation and each new session took the others over (closed sockets, "interrupted by a new session"), which also looked like freezing. Each browser now sends an anonymous `viewer_id` (`match/viewer-id.ts`); migration 045 keys conversations and sessions by (viewer, profile, match); a takeover closes only that browser's socket. Test `test_two_browsers_on_one_profile_are_two_viewers_and_never_take_each_other_over`; frontend `viewer-identity.test.ts` |
| M2 | In a demo, viewers can change their own team and narrative style (replaces the bucket lock) | frontend/backend | **fixed in code**: the live-match lock is removed (`audience-view.ts`); the feed routes by the chosen bucket, whose engine narratives (and seeds) already cover every enabled bucket, so a change shows that bucket's history up to the viewer's position. Test updated in `demo.test.ts` |
| M3 | New deploys work without a hard refresh (cache-busted assets) | frontend/nginx | **fixed in code**: viewer assets were already fingerprinted and `index.html` no-cache, but a tab opened before a deploy asked for the removed fingerprint (404 until a hard refresh). `tools/build.sh` links `/app/current`; nginx serves an old fingerprint from it, no-cache. `build.test.ts` |
| M4 | Matches froze at exactly 20′ for viewers; find and fix the cause | demo/feed | **cause found, mitigated**: the 20′ seed recording held its runs at 20′ while people watched them (recording and demoing shared the stack), and the shared session (M1) closed sockets. Recording runs are hidden from the picker (`/demo-api/state` lists them as `recording`; `demoMatches` drops them, and while a demo is live lists only its own runs; tests `demo.test.ts`, `test_demo_control.py`); a viewer inside one now sees "This match is being recorded as a demo start point and pauses there" (`showLiveFrom`). Don't record seeds during a demo |
| M5 | Non-admin Start demo did not open the match | demo/frontend | **likely cause fixed in code**: no viewer route is dev-gated; the public `/demo-api/state`/`status` limit (5/s per client key) was shared by every viewer behind the ingress or one Cloudflare node, so the second viewer's polls got 429 and the picker hid the demo controls and never opened the match; now 40/s, burst 200. Also a Start refused because a seed was recording (409) only showed a notice. **Checked on Azure 23 Oct**: an anonymous viewer pressing Start demo (60′, HT, 20′) opened Redcastle Town v Port Albion with video and insights |
| M6 | Fictional league: no Elephant League branding, invented league, club names and logos (model-made), our own clip transition instead of the third-party GIF; assess player names | data/frontend | **Built 23 Oct** (option c): fictional Elephant League. `data-generation/grf_demo/league.json` is the single source (league, six clubs, codes, colours, crests, 66 invented players); fixture keys `riverton-forgeham`, `redcastle-portalbion` (main), `skybridge-whitmore`. All three matches re-rendered with the same seeds, tactics and thresholds: events, scores and tactic changes identical to the previous renders (checked field by field); scoreboard codes and player name tags now fictional. Own CSS sting (`builtin:league`, migration 049); real crests, league fonts and logos removed. Data, goldens, fixtures, benchmark cases and active docs renamed; `legacy/`, `docs/research`, `docs/reviews` and dated benchmark results stay historical. Previous renders kept as `.local/grf-demo-*-90-pre-league`. Seeds must be re-recorded (fixture keys changed; feed migration 008 clears their start points). **Deployed 23 Oct**: new media and recordings on Azure, old real-club media and recordings removed; 20′/HT/60′/85′ re-recorded on sol (§11) |
| M7 | Clip length is uneven (short shot and own-goal clips, one goal much longer); verify the own-goal label; document and tune clip length per clip type | backend replay | **fixed in code**: an own goal's `move` lead-in started at the defender's one-touch possession, so its clip was a couple of seconds; it now starts at the attack before it (`ReplayBuilder.build`). Its caption always comes from evidence: the own-goal player and the side it counts for ("own goal (Forgeham United goal)"). Lengths vary mainly by lead-in (`move` follows the whole attack, capped at 25 s); migration 046 adds `min_clip_seconds` 8 s and keeps 5 s after a goal (was 2 s). How length is decided: `user-backend/docs/components/services.md` §5. Tests: `test_replay.py::test_own_goal_clips_show_the_attack_and_say_who_it_counts_for`, updated `test_replay_clips.py` |
| M8 | "Show me the goals from both games" answers across several matches instead of insisting on one | backend questions | **fixed in code**: the router names every live match a request is about; with two or more the agent returns `per_match` and the service answers from each at its own position (`QuestionService._answer`), returned as `parts` (each other match marked with its header; offers from every part can be tracked; one receipt for the whole answer, which costs one routing call plus one routed answer per match). Never narrowed to one or met with invented choices. The viewer shows one answer per match (`chat-view.ts`). Tests: `test_cross_match.py::test_a_request_about_both_games_is_answered_from_each_at_its_own_position`, `test_question_intent.py`, frontend `follow.test.ts` |
| M9 | Formula stats (for example take-ons in own half) answer correctly | backend questions | **checked**: "take-ons in own half" is a stat goal with a location bound (`start_x` ≤ 52.5, team-relative) and "pass success rate" a percentage of two counts; both compile to rules whose values equal an independent scan (`test_filter_engine.py::test_formula_stats_from_the_team_review_evaluate_exactly`; pass rate is also the `composite` question case) |
| M10 | Model per role is editable live in `/dev/` (sol, luna, mini); compare speed and quality and pick a default per role (latency is acceptable to the team; replays may want the stronger model) | backend/engine config | **Built 23 Oct** (tests pass; on Azure the /dev/ Models config loads with the four deployments, all roles on the service default; comparison not run yet): `backend_config.models` (migration 047, editor "Models" in /dev/) maps each role (engine summary, compression, analyst, author; backend questions, follow planner, replay) to a deployment and effort. The backend applies it within 2 s (`app.watch_models` → `adapters/llm.role_model`); the engine reads `GET /model-roles` per call and rebuilds only a changed role's agent at the same endpoint (`agents/llm.LLMAgents`). Empty deployment = the service's own setting, so local stays on its local model. Terraform adds `gpt-6-luna` and `gpt-5-mini` deployments beside the sol `writer`/`questions` (sol quota is fully used, 250/250K). Defaults stay gpt-6.1-sol for every role (team accepts its latency; replays benefit from the stronger model). Comparison method for the Azure run: for each role switch one deployment at a time in /dev/, run a seeded 20′ demo for 10 match minutes, record engine lag, drop/trim rate and a blind read of 10 outputs per model; keep sol unless luna matches quality at lower lag. Tests: `user-backend/tests/test_model_roles.py` (5), `narrative-engine/tests/test_model_roles.py` (2). Review fix: a role with a deployment but no effort keeps the service's effort, so Foundry models never get the chat call's temperature 0 (`test_model_roles.py`) |
| M11 | Narratives read as one story: each author step sees the previous insights for its bucket or follow | engine | **Already in place, tightened**: shared insights get the bucket's last 5 narratives up to the step's horizon (`narrative_excerpts`, covered by `test_orchestrator.py`), follows get the topic's earlier narratives (`story_so_far`); bucket excerpts now carry their minute (`context/builder.py`) like follows, so the author can read them in order |
| M12 | Narrative length as its own layer next to team and style (Brief / Standard) | backend config | **Built 23 Oct**: migration 047 adds a `length` layer (Standard, Brief) to every template and match catalogue; existing buckets keep their ids and select Standard; a disabled Brief twin of each is added (enable in /dev/). The author reads the option's description through the bucket framing (data, no prompt rule). Standard is `in_label: false`, so bucket names stay "Riverton Rovers · Analytical"; Brief shows "… · Brief". Tests: `test_model_roles.py`, `test_audiences.py`, `test_migrations.py`. On Azure 23 Oct the layer is present in every fixture's audience config |
| M13 | Demo fast-forward: jump ahead (for example +20′) by punching seeded or recorded events through fast, backfilling follows, video skipped; demo adapter only | demo | **Live-checked on Azure 23 Oct**: +10′ and +20′ jumped the video at once and the pipeline caught up within about 2 minutes; followers kept their follows. The control was hidden once the match connected (fixed, §11). Design: "Skip ahead" in the match view (targets from `skip_targets` in the feed's demo settings, migration 007: +10′, +20′, second half) → `POST /demo-api/skip` → feed `/demo/skip` (DEMO_SEEDS only). Every demo run's kickoff moves back by the same whole minutes, so the runs keep their matchIds, stagger, main-first order, follows and sessions; the feed sends what became due at once in capped sends through the normal pipeline (ETL, engine, backend), video publishes to the new clock and the player's live catch-up seeks to the edge; the engine summarises the skipped minutes in order (MinuteClosed catch-up), so followers get their narratives through the normal path. Chosen over chaining seeds: no new matchIds, any target. Tests: feed 4 (shift, no future data, contiguous seqs, point rounding, refusals, settings) + Postgres repository; demo control 1; frontend 1; nginx route test. Not measured live: about 4,100 items per match per 20′ (about 12,000 for three) reach Event Hubs in roughly 15 s at the emulator's ~1,000 events/s; the narratives then trail by however long the model takes to summarise 20 minutes per bucket (minutes on the local model, less on Azure). On Azure, Stream Analytics adjusts the back-dated timestamps (late arrival 5 s), so the skipped minutes close together. |
| M14 | Replay the events behind a formula stat (for example keeper punches, take-ons in own half) | backend replay | **fixed in code**: the replay search takes the same location bounds as a stat (`find_events(locations=…)`), and its instructions say the history's goal holds an earlier statistic's filters; keeper punches were already a SPADL type. Test `test_replay.py::test_events_behind_a_location_stat_can_be_found_for_a_replay` |
| M15 | Field-tilt answers match ETL's served value (looked invented) | backend questions | **fixed in code**: field tilt is an ETL trend, which the question agent never saw, so it reworded narrative prose or computed its own share. It now gets ETL's enabled trends at the snapshot (`trendsAtSeq` via `etl_dab.trends_at_seq`) as `trends` with citable `trend:` evidence carrying the value, grouped per trend (about 2K tokens, not 10K for 190 flat rows) and kept out of the replay agent; the router sees trend names (no values) and routes a trend-only measure to `match`, not the statistic planner. Tests `test_cross_match.py::test_a_trend_question_sees_etls_served_value_and_can_cite_it` (bounded at the viewer's seq), `test_question_intent.py` |
| M16 | The viewer never shows a raw exception | frontend/backend | **fixed in code**: `MatchApi.request` and `DemoApi.call` turn network and timeout failures into plain sentences; every viewer error goes through `friendly()` (only our own service messages pass; any other exception shows "Something went wrong. Please try again."); demo control no longer puts the seed error text in its 409/503 details (logged instead). `viewer-identity.test.ts`, `demo.test.ts` |
| M18 | A follow's half-time wrap-up is posted once, never repeated (check `period_end_wrap_up`) | engine follows | **Checked 23 Oct**: once per topic, bucket and period: each period end is queued once (`closedPeriods`), its decision is pinned by trigger ref (`subdec:{match}:{ref}`) and each narrative by step id, so retries and restarts resend the same narrative; catch-up never wraps up. Test: `test_follows.py::test_a_period_wrap_up_posts_once_per_topic_bucket_and_period_across_retries_and_restarts` (run with injected publish failures and a restart, live and backlog) |
| M17 | No pipeline stage drops out mid-demo (keep apps warm while a demo is live on Azure) | Azure infra | **partly**: the keep-warm loop held every stage through 60′ and HT demos (about 40 min, no stage dropped). Open: demo control itself cold-starts in about 40 s on a first visit (§11) |
| M19 | Seeded Start demo took ~101 s on Azure (restore ~5 s; ~96 s purging the previous demo's finished runs owner by owner, run by run, plus waking idle apps) | demo control | **Measured on Azure 23 Oct: 60′ seeded start 8.1 s** (was 11.1 s before seeds in memory and 1 vCPU; 20′ 3.7 s server-side; §11). Built 23 Oct: finished runs are swept from ETL, engine and backend between demos by the keep-warm loop; any left are purged at Start in parallel (every run x owner at once) alongside run creation and the seed restore, joined before release so viewers only list the new three; Start also wakes `DEMO_KEEP_WARM_URLS` apps; Cancel purges the feed then the others at once. Mocked latencies (owner purge 8 s, restore 1.5 s): 75.5 s before, 8.2 s unswept, 3.7 s swept. Tests: demo control 22 passed. Review fix: the sweep purges only once no demo is live and a run has been finished `DEMO_SWEEP_GRACE_SECONDS` (900 s), and purges outside the start/cancel lock; Start's cleanup has its own worker (tests: live demo never swept, cancel never waits on a sweep; demo control 24 pass) |
