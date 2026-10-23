# InsideTheGame: plan, decisions and progress

> **In short:** the living record of what was decided and why, what the demo must achieve, what is proven, and what is still open. The submission closes 27 Oct 2026, 11:59 pm PT.

| | |
| --- | --- |
| **Branch** | `integration/luke-services`, merged to `main` |
| **Last updated** | 23 Oct 2026 |
| **Now** | Demo build deployed on Azure (fictional league, every agent on `gpt-6.1-sol`, all four seeds recorded); repo cleanup |
| **Next** | Remaining acceptance checks (§10.4), then the submission items (§8) |

## 1. Goal

*In short: one production-shaped flow, local and Azure, from a simulated provider to the viewer.*

Wire the ETL and narrative engine into the app as a full flow fed by our GRF match data:
- narratives only for the audience buckets the backend has enabled;
- prompts and tunables in the database, edited live in `/dev/`;
- several matches at once;
- deployable to Azure with one command.

## 2. Architecture

*In short: built as planned; see the [README](README.md) and [architecture.svg](architecture.svg).*

The feed is an external provider (Event Hubs + HLS over HTTP); the ETL is the only match-data owner (Stream Analytics → Azure SQL → DAB GraphQL); SPADL is the action language; the engine writes per enabled bucket; the backend routes narratives unchanged. Every service is deployed with `./dev azure up` ([terraform/docs](terraform/docs/README.md)).

## 3. Decisions

*In short: what was chosen, by the developer unless marked.*

| Date | Decision |
| --- | --- |
| 20 Oct | Never name the local development LLM provider, its hosts or model families in files. Azure AI Foundry and Azure model names are welcome; the judging rewards them. |
| 20 Oct | Real demos and showcases start from kickoff (00:00). |
| 20 Oct | Prod-ready: no stubs or hard-coded data on the live path; tunables live in the owning service's DB and `/dev/`; future data must be physically unreachable. |
| 20 Oct | Several matches run at once; every layer is keyed by a run-scoped `matchId`; purge is per match. |
| 20 Oct | The feed simulates an external provider: our services see only Event Hubs and HLS over HTTP. |
| 20 Oct | One ETL pipeline; the demo ETL stand-in is deleted. |
| 20 Oct | No "sides": the whole codebase is ours to fix, including ETL, engine, Azure infra and telemetry. |
| 21 Oct | Audiences are config-only: layers → buckets with descriptions, enabled in `/dev/`; viewers pick from enabled buckets; no viewer presence. |
| 21 Oct | Spin Azure down when not testing; we run the Azure test ourselves. |
| 21 Oct | Fail visibly without a model; prompts stay global; the lab recording upload is removed. |
| 21 Oct | SPADL is the action language across the stack. The backend reads SPADL from ETL via GraphQL. Every stat is redefined on SPADL (126 ids); `shots_saved` counts real goalkeeper saves. |
| 21 Oct | Agents get SPADL definitions in context plus a `lookup_spadl` tool; we optimise for accuracy, not tokens. |
| 21 Oct | Narratives are storylines that develop through the game, grounded in multi-minute trend analysis, not last-minute commentary. |
| 21 Oct | Story follows use Microsoft-Decision-1 (Foundry); one follow per viewer; pivotal key moments for everyone (§6). |
| 22 Oct | The demo always runs exactly three matches from a "Start demo" picker (kickoff, 20′, HT, 60′, 85′); mid-match starts restore seeds recorded on Azure, then run live; Cancel demo purges and returns to the picker. (The bucket lock during a demo was removed 23 Oct, §12 M2.) |
| 22 Oct | Matches are tactically scripted per fixture (press, block height, flank, directness, fatigue, game state) so multi-minute patterns are real. |
| 22 Oct | Spend: budgets email only (A$15/day monthly, and the trial credit); never auto-stop on the daily cap. The one automatic action is a last resort at 90 % of the credit that stops Stream Analytics, the feed and SPADL but keeps the viewer and replays up. Stream Analytics runs only while match events flow. |
| 22 Oct | Redcastle Town–Port Albion is the main demo match at full video quality; the other two upload re-encoded at about 1.75 Mbit/s. |
| 22 Oct | The demo build sets `demo_seeds` (DEMO_SEEDS=1 on feed, ETL admin, engine, backend; seeds on an Azure Files share); `./dev azure up --release` turns it off. |
| 22 Oct | Every live agent on Azure runs on `gpt-6.1-sol` (`writer` for the engine, `questions` for the backend), effort `low`; Decision-1 for claim checks and triggers. Local demos keep the local model. |
| 22 Oct | Team review: the simulated matches stay as they are (the data is swappable); the generator is not tuned further. |
| 23 Oct | Fictional league (§12 M6): invented league, clubs, players and artwork; recordings re-rendered with the same seeds. |
| 23 Oct | Demo control keeps one replica warm through judging (a cold picker took about 40 s). |
| 23 Oct | Docs only in each service's `docs/` plus one README; code and tests never cite PLAN sections or review tags. |

## 4. How we review

*In short: rounds of independent agents that read, run and fix, until a round finds nothing.*

- A **system agent** owns the shared local stack (`itg-local`): rebuilds, starts three matches and follows them with headless viewers, checking stats against each recording's ground truth, narratives, questions, replays, video, purge, restarts and `/dev/` changes.
- **Area reviewers** read every changed file against the plan, contracts and hackathon rules, run every suite in throwaway containers, fix at the source and report.
- The brief: no commits or checkouts; never print secrets; no provider names; only the system agent touches the shared stack; at most two heavy jobs at once.
- Seventeen rounds ran (to 22 Oct); their findings are fixed and live in git history. Later work is checked on Azure as an anonymous viewer (§11).

## 5. Storylines

*In short: deterministic trends, an analyst that names grounded patterns, and storylines the author develops. Deployed.*

- **Trends (ETL):** possession, field tilt, territory, pressing, entries, shots, fouls, momentum and more over the last 5, last 15, half and match, with thresholds in `trendDefinitions`; SQL and a Python reference in parity ([trends](etl/docs/components/trends.md)).
- **Analyst** (every 5 minutes, shared, neutral) finds patterns in its own words, each citing the numbers behind it; a validator checks those numbers. **Storylines** open, develop and resolve per match; the author advances them in each bucket's framing.
- **Honesty check (21 Oct):** on GRF data, minute-to-minute play behaves like independent draws; half- and match-level control is real. So spells, momentum and fast breaks are seeded `enabled = false` and storylines come from half/match control plus key events.

## 6. Story follows

*In short: viewers follow stories; Decision-1 decides when a story moves; only followers get it. Deployed.*

- A follow chat in the follow view proposes a story; the viewer confirms. One follow per viewer per match; identical follows share generation; late followers get "the story so far"; HT and FT wrap-ups.
- Triggering: a rule-based prefilter, then one batched Decision-1 check per match per update (Decision-1 limits requests, not questions). A constrained-LLM classifier is the fallback behind the same adapter.
- Followers see their story in their bucket's framing instead of the shared insights; "Stop following" restores them.
- Key moments for everyone: short centred lines for goals (with scorer), red cards and second yellows, penalties, VAR overturns, kick-off/half-time/full-time, e.g. "Goal · Riverton Rovers", "Red card · Jorge Palmeira".

## 7. Timeline

*In short: what is left, Brisbane time.*

| When | What |
| --- | --- |
| 24–26 Oct | Remaining acceptance checks (§10.4); video |
| 27 Oct | Submission (11:59 pm PT); the build stays up until judging ends (11 Nov, 5:59 pm AEST) |
| After 11 Nov | `./dev azure down` |

## 8. Needs the developer

- Confirm hackathon registration and team eligibility (registration closed 20 Oct).
- Demo video under 2 minutes (public YouTube or Vimeo), the project pitch naming the Microsoft technologies and the description; check every submission requirement. Judge access must stay free and working until 10 Nov, 11:59 pm PT.
- Make the repo public; choose a licence.
- Foundry quota in Australia East (`gpt-6.1-sol` GlobalStandard 250K TPM: `writer` 120K + `questions` 130K; `Microsoft-Decision-1` DataZoneStandard 50 RPM).
- Whether to clean old provider names and real-club names from git history.
- Create the `BUNDLE_DENYLIST` CI secret.

## 9. Known limits

- On the shared local model, three concurrent matches put narratives minutes behind; Azure capacity or fewer enabled buckets fixes it.
- Momentum and fast breaks stay off as claims (too few shots per GRF match to test them); pressure spells are a weak signal, served only alongside territory.
- Decision-1's dev deployment allows 10 requests a minute, so three matches with rewrites lag locally; Azure's allows 50 (`DECISION_REQUESTS_PER_MINUTE`), and each request batches every claim of a step.
- After a hard host restart the local Cosmos emulator can keep a stale `postmaster.pid`; remove it inside the container and restart that container.
- Stream Analytics takes 75–90 s to start on Azure; the viewer's clock follows ETL's watermark on purpose, so the first minute after a cold start lags.
- Cancel purges for minutes after a long demo (3 min 19 s after a 60′ demo skipped to 80′; feed HLS blob deletes and ETL dominate).

## 10. Demo build

*In short: what judges see, the targets each part must hit, and how we prove it on Azure before submission.*

### 10.1 Goals

- A judge opens the URL, presses **Start demo**, picks a start point and within seconds watches three live matches with a rich story so far.
- Everything they see is generated by the deployed pipeline (Foundry models, Decision-1 checks), with no future data and honest labels.
- The build idles cheaply until judging ends and never runs out of credit.

### 10.2 Features and order

| Phase | Feature | Status |
| --- | --- | --- |
| D1 | **Start demo**: three matches (main game `redcastle-portalbion` first), start-point picker, joins a live demo, one demo under concurrent clicks, **Cancel demo**, seven-stage start progress | Deployed; checked on Azure |
| D2 | **Seeds**: each start point recorded on the pipeline and restored through each owner's demo adapter, then live; "story so far generated earlier on this pipeline; live from N′" | Deployed; 20′, HT, 60′, 85′ recorded on `gpt-6.1-sol` |
| D3 | **Moment clips in follows**: Decision-1 picks rare, relevant moments (goal, penalty, red card, VAR) for a follow's playlist | Deployed; checked on Azure (48′ own goal as a capture card) |
| D3 | **Clip transitions**: hold, sting (`builtin:league`), cut, fade between clips | Deployed; reduced motion holds and cuts |
| D4 | **Slow motion** into and out of the key moment | Deployed |
| D5 | **Cross-game**: ask about, pin from and follow another live match; yellow outline and that match's header; each match read at its own position | Deployed; checked on Azure |
| D5b | **Follow this story?**: a story answer offers a follow (Decision-1 yes/no; thresholds in `follow-offer`); never automatic | Deployed; checked on Azure |
| D6 | **Capture**: clips as feed cards in the follow view, with preview cards (gradient, crest, minute, event, player, score after) | Deployed; checked on Azure |
| D7 | **Key-event clips in shared narratives** for every viewer of the bucket | Deployed |

### 10.3 Targets

| Area | Target | Measured |
| --- | --- | --- |
| Start | Picker to first frame and story so far within 10 s (seeded starts); kickoff start shows the first narrative by 2′ | Seeded 60′ start 8.1 s, 20′ 3.7 s server-side on Azure; picture about 20 s after Start |
| Lag | Engine narratives at most 2 match minutes behind on three concurrent matches | About 0.5 minutes on `gpt-6.1-sol` |
| Grounding | Excerpts dropped or trimmed under 15 %; no wrong-direction comparison or wrong score accepted (sampled) | Not measured on Azure |
| Follows | Catch-up within one minute of following; HT and FT wrap-ups reach every follower | Catch-up about 10 s; HT wrap-ups in all three matches |
| Isolation | No text names another match's teams; no read past a viewer's seq | No breach in scans |
| Cost | Idle A$3/day or less; one session (three matches to HT) A$2 or less; total through 11 Nov within the credit | Missed: idle about A$7–8/day (demo control warm), a session about A$3; within the credit |
| Availability | URL works from a fresh browser on an unknown IP, no login; cold start under 30 s | Met (anonymous viewer through the edge) |

### 10.4 Azure demo acceptance (before submission)

1. `./dev azure up` from clean; spend budget and guard in place. **Done.**
2. Seeds recorded (D2) on `gpt-6.1-sol`. **Done.**
3. From a fresh browser: Start demo at each start point, plus kickoff; Cancel demo between them. **20′, HT and 60′ checked; kickoff and 85′ open.**
4. Check every §10.3 target and the D1–D7 rows; screenshot each. **Partly (§10.3).**
5. Leave idle for 12 h; confirm idle cost and that the next Start demo cold-starts within target. **Open.**
6. Record results here; fix and repeat any failed row.
7. Docs and diagrams cover D1–D7. **Docs done 23 Oct; diagrams regenerated when their content changes.**

### 10.5 Judge build

Stays up from submission until judging ends (11 Nov, 5:59 pm AEST): free, no IP allow-list, no login. Budget alerts by email only; the last resort (actual spend at 90 % of the credit) stops Stream Analytics and the feed while the viewer stays up. `./dev azure down` after 11 Nov.

### 10.6 Demo control and seeds

*In short: built and deployed; the design lives in [local/docs/components/demo-control.md](local/docs/components/demo-control.md).*

Demo control is the operator between the provider and our services (start, cancel, skip, status, seed record and restore); seeding lives in one demo adapter per owner, mounted only with `DEMO_SEEDS=1`. Open: one viewer's Cancel stops the demo for every viewer (as asked); an in-page dialog guards it.

### 10.7 Local integration check (22 Oct)

*In short: D1–D7 checked end to end on itg-local with all four seeds re-recorded; local model.*

Passed. Fixed then: seeded start time (engine batch restore, backend parse off the loop), replay evidence on restored matches, indicator jargon in insights (ETL migration 018). Open: replay questions on the local model sometimes cite moments without searching.

### 10.8 Local check on the fictional league (23 Oct)

*In short: every suite passes and the full flow works on itg-local with the Azure seeds.*

Passed: seeded 20′ start, questions, cross-match follow, Skip ahead, capture card, Cancel, live `/dev/` config changes. Fixed then: Azure seeds refused locally (stand-in table in the fingerprint), `/dev/` prompt and audience saves.

## 11. Azure judge build

*In short: deployed at the azurecontainerapps.io URL and msft-hackathon.koda-software.com; redeployed 23 Oct with the fictional league; all agents on `gpt-6.1-sol`; all four seeds recorded; checked as an anonymous viewer.*

- **Deployed:** 5c377c6 (demo build, image `v20261023114741`); edge `UPSTREAM` unchanged.
- **Fixed while deploying:** Stream Analytics query compile error and output casts; Stream Analytics out of memory (10-minute lookback, 4 h sessions); resource-group budgets left behind by `down`; the guard's Automation account in East US (Free Trial); serverless SQL resume retries; media upload with azcopy and re-encoded secondary matches; Responses API for reasoning models with tools; the backend's follow check on Decision-1; Skip ahead hidden after connect; follow planner without the other match's score; a goal against a followed team not firing (score before and after in the update); "footage unavailable" after a seeded start; native `confirm()` on Cancel; stream-start webhook on Start; `./dev azure plan` parity with `up`.
- **Verified as an anonymous viewer:** three matches, main game first, video and seeded insights; questions in about 6 s; cross-match answers with a follow offer; cross-match follow with catch-up in about 10 s; a capture card played as a replay; Skip ahead +10′/+20′; Cancel; a 69′ equaliser now firing a follow narrative.
- **Measured:** seeded 60′ start 8.1 s (restore 5.2–5.8 s); engine lag about 0.5 minutes; about US$2 of tokens per session of three matches to half time; idle about A$6–7/day plus the warm demo control.
- **Open:** grounding not sampled on Azure; the 12 h idle check; kickoff and 85′ starts from a fresh browser.

## 12. Team review actions (22 Oct meeting)

*In short: everything the team asked for after using the Azure demo; each row closes only with evidence.*

| # | Action | Status |
| --- | --- | --- |
| M1 | Two browsers must be two viewers | Fixed: an anonymous `viewer_id` per browser; sessions keyed by (viewer, profile, match) |
| M2 | Viewers can change their own team and narrative style in a demo | Fixed: bucket lock removed |
| M3 | New deploys work without a hard refresh | Fixed: old fingerprints served from `/app/current` |
| M4 | Matches froze at exactly 20′ | Mitigated: a seed recording held its runs; recording runs are hidden from viewers. Don't record during a demo |
| M5 | Non-admin Start demo did not open the match | Fixed (demo-api read limit 40/s); checked on Azure |
| M6 | Fictional league: invented league, clubs, players, logos and clip transition | Deployed 23 Oct; seeds re-recorded |
| M7 | Even clip lengths; own-goal label | Fixed: own-goal lead-in, `min_clip_seconds` 8 s |
| M8 | "Show me the goals from both games" answers from each match | Fixed |
| M9 | Formula stats answer correctly | Checked |
| M10 | Model per role editable live in `/dev/` (sol, luna, mini) | Built and deployed; defaults stay `gpt-6.1-sol`; comparison not run |
| M11 | Narratives read as one story | In place; excerpts carry their minute |
| M12 | Narrative length as its own layer (Standard / Brief) | Deployed; Brief disabled by default |
| M13 | Demo fast-forward | Deployed: Skip ahead +10′, +20′, second half; live-checked on Azure |
| M14 | Replay the events behind a formula stat | Fixed |
| M15 | Field-tilt answers match ETL's served value | Fixed: the question agent sees ETL trends |
| M16 | The viewer never shows a raw exception | Fixed |
| M17 | No pipeline stage drops out mid-demo | Fixed: keep-warm loop; demo control min 1 replica |
| M18 | A follow's half-time wrap-up posts once | Checked |
| M19 | Seeded Start demo took about 101 s on Azure | Fixed: 8.1 s (seeds in memory, sweep between demos, parallel purge) |
