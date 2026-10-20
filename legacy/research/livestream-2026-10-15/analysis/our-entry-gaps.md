# Our entry vs the livestream bar

Written 20 Oct 2026, with submission closing 27 Oct 11:59 PM PT. Inputs: `judge-lens.md`, `reference-repo.md`, `winner-profile.md` and our repo (read-only; nothing was run). Feature states follow AGENTS.md: **planned / implemented / tested (local) / deployed**. Nothing is deployed.

## 1. Where we already match or beat the bar

- **Synthetic, live, event-level data, which Benz's demo lacks.** It is a seeded Google Research Football (GRF) render: Chelsea 2–1 United, 11,392 Opta-style feed messages, a broadcast clock, the raw SHA-256 embedded, rejected seeds listed, and realism deviations disclosed. See `data-generation/recordings/README.md` and `data-generation/docs/grf-demo.md`. His data is static real Kaggle results. *Tested (local).*
- **"As they happen".** A replay clock feeds the Event Hubs emulator, which feeds ETL and the backend independently. See `etl/README.md` and `local/README.md`. *Tested (local, emulators); not deployed.*
- **Code computes, model explains.** ETL owns every standard stat (`etl/demo_etl/services/statistics.py`). The question router never sees values (`user-backend/docs/question-agent.md`). Custom stats compile to a bounded DSL with no generated Python (`user-backend/docs/local-llm.md`). Standard stats never pass through the model, but answer prose is not number-checked (gap 5), so his per-answer check is stricter than ours. *Tested (local).*
- **Evidence IDs are validated.** A match answer that cites unknown evidence is rejected (`user-backend/backend/agents/question_contracts.py:52-55`). Replay clips are cut by code from agent-chosen evidence IDs (`user-backend/docs/replay-plan.md`). A narrative is released only if the hash of the events so far matches the one it was written from, and none of its evidence has since been corrected (`narrative-engine/fixtures/README.md`). Like his, evidence is checked per answer, not bound to each number. *Tested (local).*
- **A refusal path exists.** There is an `unsupported` route (`user-backend/backend/agents/question_intent.py:53`, `question.py:37`), measurement-support contracts and coverage-aware clarification (`user-backend/tests/test_measurement_support.py`). His refusal names the missing data; ours does not yet (see §3 and action 5). *Tested (local).*
- **Bounded agents.** Max 6 tool calls, `QUESTION_TIMEOUT_SECONDS=90`, `QUESTION_MAX_ACTIVE=4` and `AGENT_MAX_REPAIRS=3` (`user-backend/docs/question-agent.md`). The 6-call cap matches his; our 90 s timeout and 1,600-token answer cap (`question.py:75`; 3,000 on the routing call) are looser than his 45 s and 1,200 output tokens. *Tested (local).*
- **Multi-agent on Microsoft Agent Framework.** Separate goal, question and replay agents plus a deterministic compiler (`user-backend/backend/agents/workflow.py`, `question.py`, `replay.py`). He rejected Agent Framework and shipped a single agent, so this is a category edge. *Tested (local; local model or fixtures, not Foundry).*
- **Personalisation.** 3 allegiances × 4 styles give 12 audience buckets ("audiences" below), and the same moment is framed per audience (`user-backend/README.md:34`). He has none. *Tested (local).*
- **Honest labelling.** The viewer footer reads "Simulated match with pre-written AI narratives · Not an official Premier League product" (`frontend/match/index.html:244`). The readiness doc separates built from remaining work (`docs/reviews/hackathon-readiness.md`). *Implemented.*
- **IaC exists.** Terraform with mock-provider tests (`terraform/README.md`). *Tested (local, mock provider); never applied.*
- **Eval scaffolding exists.** `user-backend/benchmarks/evaluate_questions.py` has 10 question cases still bound to an old Madrid recording; the 100-rule filter corpus is `benchmarks/cases.py` (+12 ambiguous/unsupported prompts); plus `./dev benchmark replay`. A dated local-model comparison exists (`user-backend/benchmarks/results/model-strength.md`, 18 Oct); no Foundry/Azure model comparison yet. *Implemented (tooling only).*

## 2. Gaps ranked by judging impact

| # | Gap | Current state | Impact | Effort |
|---|---|---|---|---|
| 1 | **No judge access**: localhost, private repo | planned | fatal | L |
| 2 | **No video** | planned | fatal | M |
| 3 | **Third-party rights in git and on screen** | present in git | high (§4.4/§4.6; Benz's top theme) | M |
| 4 | **Model is not on Foundry/Azure** | planned | high ("running on Azure is the goal") | M |
| 5 | **Receipts not visible in the viewer** | implemented (lab only) | high (his most demo-able trust signal) | S–M |
| 6 | **No cost/latency/token display, trace view or telemetry** | planned | medium–high | M (capture + display) / M (OTel) |
| 7 | **README is a dev doc, not a submission doc** | planned | medium | S |
| 8 | **Live narratives are offline-authored** | implemented (offline fixtures, labelled) | medium; label it, don't build it | L (skip) |
| 9 | **No measured Foundry model choice** | planned (local-model comparison only) | medium | S–M |
| 10 | **No keyless/managed identity** | planned | low–medium | M |
| 11 | **English only** | out of scope | low | skip |
| 12 | **Large uncommitted diff on `main`** | present (uncommitted) | low, but blocks a clean public repo | S |

1. Localhost only, and the GitHub repo is **PRIVATE** (`gh repo view`). §4.4 requires a public repo for the entry to be considered, and §4.8 requires judge access.
2. None under 2:00 on YouTube/Vimeo.
3. PL fonts, PL and Microsoft logos and club crests are committed (`frontend/assets/league/`; PROVENANCE.md says it is "not a licence grant"). Real player names (James, Šeško, Mainoo) appear as on-pitch name labels burned into the rendered video and in the recording (shirts carry numbers only).
4. The live path is a local OpenAI-compatible endpoint, and the default is `fixture` (`user-backend/docs/local-llm.md`).
5. Evidence labels show only in the lab chat (`frontend/lab/chat-view.ts:39`), not the match viewer. Prose numbers have no checker (MatchAnswer text is unvalidated). No "N numbers checked" badge.
6. No OTel/App Insights. Grep found no telemetry code outside `terraform/main.tf`; runtime code reads no token usage.
7. It lacks a pitch, named category with clause evidence, demo/video links and attribution near the top. There is **no root LICENSE**, and `.github/workflows/` is empty (no CI).
8. Not runtime AI (`narrative-engine/README.md`). Explain/Render rest on fixtures plus the question agent.
9. Local models were compared on 18 Oct (`results/model-strength.md`), but no Azure/Foundry deployments.
10. Terraform uses a DB admin password.
11. No i18n.
12. Per git status.

## 3. Specific risks

- **Data provenance and licensing**
  - GRF is Apache-2.0, and the Gameplay Football engine is Unlicense, but the rendered *assets* "retain their original provenance" (`data-generation/docs/grf-demo.md:41`). Check the asset licence before hosting the video publicly.
  - The narratives were AI-authored from GRF video contact sheets, i.e. our own render. That is fine if stated, and it should appear in the README, not only in `narrative-engine/fixtures/README.md`.
  - Real player names on synthetic play put words in real people's mouths. Benz's liability rationale for the synthetic rule [16–17] points straight at this. Swap in fictional names or explicitly justify them.
  - Committed PL fonts and logos are redistribution of proprietary files. Making the repo public publishes them in history, so publish a fresh history or purge them first.
  - `legacy/competitors/` holds 19 files: reviews of 20 competitor repos plus a project catalogue. Exclude them from the public repo or confirm their licences.
  - Credit Google Research Football in the README right after the pitch, which is Benz's "front page" rule [24].
- **Demo accessibility (§4.8)**
  - Everything runs on loopback (`local/README.md`). The stack is "unauthenticated", which is fine for judges but needs rate limits and a model budget cap.
  - **One active session per profile, and a new tab takes over** (`user-backend/README.md`). Two judges on the same profile will kick each other out. Use a per-visitor demo identity or a profile per visitor.
  - **One shared 90-minute real-time replay.** Judges land at a random minute or after full time. Auto-loop it, or offer a judge "start at minute N".
  - The HLS video is ignored (`.local/`) and must be hosted.
  - The Microsoft emulators carry EULAs, and their use in a public deployment is unverified. Prefer real Event Hubs and Service Bus (Basic/Standard).
- **Azure deployment**
  - Status is zero. Terraform is "foundation scaffold; not deployed" and lacks networking, identities and images (`terraform/README.md`, `terraform/deployment-readiness.md`).
  - With 7 days left, the realistic minimum is one ACA environment (or a VM running Compose) with real Event Hubs, Service Bus and a Foundry model. Keep Postgres for ETL; Azure SQL/Cosmos is too much this week. Label the substitution.
- **Visible grounding and receipts**
  - Validation exists server-side but is invisible.
  - Show three things per answer: evidence chips, a "grounded: N facts from ETL" badge and a stat-source line on the cards.
  - Add a cheap numeric check of answer prose against the cited evidence or stat values. On failure, hide the prose and show the stat, mirroring his `fallback` status.
- **Refusal behaviour**
  - It is tested (local), but the reply is only "Sorry, I cannot answer that". Make it say *what data is missing* (e.g. "this recording has no tracking speed").
  - Fixture mode refuses anything off-script. If the deployed demo falls back to fixture, judges hit refusals constantly, so it must run in model mode.
- **Cost/latency display**
  - None yet. Runtime code reads no token usage (`user-backend/backend/adapters/llm.py` only sets `max_tokens`); only `user-backend/benchmarks/model_observer.py` does. Capture usage, then surface latency, tokens and estimated cost per answer from a dated price table.
  - Put the shared-narrative point in the README: one model pass serves every viewer, not one per viewer.
- **Video under 2:00**
  - No script and no take exists.
  - The rights issue in point 3 above also applies to the footage: PL crests and fonts on screen, plus real names as burned-in on-pitch labels.
  - Pre-record. Do not show localhost or fixture mode as AI.

## 4. Top 7 actions this week

**First: confirm registration today (closes 20 Oct 12:00 PM PT, rules §1).**

1. **Rights clean-up (Tue).** Replace PL fonts and logos and club crests with our own marks. Rename the players to fictional names, then re-render the video (the labels are burned in) and re-package the recording (narratives bind to the recording hash, so rebind them). Create a fresh public repo history without the proprietary files or `legacy/competitors`. Add a root LICENSE and a README attribution line for GRF.
2. **Deploy to Azure (Tue–Thu).** Use ACA (or one VM with Compose) for backend, ETL, narrative and nginx, with real Event Hubs, Service Bus and a Foundry model deployment. Set a budget alert. Rate-limit asks. Make the replay loop. Give each visitor their own identity.
3. **Model mode on Foundry by default** in the deployed build. First rebuild `question_cases.json` for Chelsea–United, then run `evaluate_questions.py` on two deployments and record dated pass rate, p50/p95 latency and cost per answer.
4. **Receipts in the match viewer.** Add evidence chips, a "grounded N" badge, latency/tokens/cost per answer and a numeric prose check with a visible fallback status.
5. **Make refusals specific.** Name the missing data. Rehearse one out-of-scope question for the video.
6. **Rewrite the README as the submission page.** Include a pitch, the 5 stages mapped to files, the named category (multi-agent on Agent Framework) with clause evidence, the live URL, the video, synthetic/authored-narrative disclosure, a "code computes, model explains" slogan and planned vs working. Add a minimal CI (pytest plus tsc).
7. **Video (Sat–Sun).** Follow [winner-profile.md §5](winner-profile.md#5-video-skeleton-under-155-his-order-compressed). Record on the deployed URL from a fresh browser, test the URL on an unknown IP, and submit by **Mon 26 Oct** (a day of slack).
