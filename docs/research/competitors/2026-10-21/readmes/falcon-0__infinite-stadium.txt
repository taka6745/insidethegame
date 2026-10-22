# Infinite Stadium

A synthetic football match companion for fans. Follow a chance, understand why it matters, replay its buildup, and trace the story to current received evidence.

This is a working development prototype for the Inside the Game hackathon. The website is hosted at https://infinite-stadium-lime.vercel.app with Azure match conversation. Studio has been removed from the site; the submitted experience focuses on Watch. Final video upload, trial continuity and submission remain pending.

## Current viewing workflow - October 14

Watch opens with a compact list of twenty synthetic fixtures across five authored passage families. Choose a match, follow passes, receptions, shots and saves at a fixed 2× replay pace, and ask football questions while playback continues. Shirt markers, a compact statistics rail and a short live action headline keep attention on the match. These are two-minute passages, not full-match video streams.

The AI interprets the question and plans read-only queries or a typed calculation. The application supplies verified facts; AI selects the relevant facts and can add a separately identified interpretation. A model reviewer checks whether the result answers the actual question and supports every claim. Supported unique fact lookups and typed calculations take two calls, including review; other questions usually take three. One bounded correction cycle can bring a request to five calls; provider failures do not retry. Queries compose player, team, action, outcome, foot, assist and pass-technique filters with exact time windows, ordering, counts and grouping. They support both positive findings and proved absence. Questions capture the displayed match time, with two previous turns available for follow-ups; playback continues. Technical sources stay out of the fan screen.

English, Spanish, French and Portuguese selections reach the match-answer workflow. Curated football-rule references currently render in English and declare their actual language. Source-bound cloud tests retain failed, partial and successful answers; they do not establish broad reliability or native-language validation. See the [submission evidence](docs/SUBMISSION.md) and [development history](docs/DEVELOPMENT_HISTORY.md).

Instant play-by-play, short automatic context and recorded recaps are deterministic. Open chat needs Azure. Legacy producer and local-inference source is retained for reproducibility; it is outside the submitted fan workflow.

The public source and downloadable demonstration are at [GitHub](https://github.com/falcon-0/infinite-stadium) and its [demo release](https://github.com/falcon-0/infinite-stadium/releases/tag/v0.1.0-demo). The release video shows a superseded Watch/Studio prototype. A Watch-only final recording is being prepared; do not use the historical clip as the final product demonstration.

## Run and explore

Use Node.js 24, the release-tested runtime. No package installation, credentials or model are needed for the recorded experience:

```sh
npm start
```

Open `http://127.0.0.1:4173/`. [Judge setup](docs/JUDGE_SETUP.md) is the authoritative guide to the source build, isolated package verification and deployment prerequisites.

1. **Choose:** select Northbridge-Harbour, Kingsport-Riverside or Eastvale-Westhaven from the match lobby.
2. **Watch:** press **Play match**. Watch uses 2× playback, so a two-minute passage takes about one minute. Compact statistics follow the current match.
3. **Follow:** the banner follows received actions at the displayed replay time. Shirt markers and the ball show the schematic passage.
4. **Ask:** with available Azure, type a football question in **Ask about the match**. Playback continues; the question captures its match time. The language selector also supplies the requested AI response language.
5. **Recap:** finish the passage and choose **View recap**. The recorded recap is automatic; AI recap generation is a separate provider request.

Useful timestamps in the default passage: the shot at **01:36** is corrected from off target to saved when received time reaches **01:38**. The goal at **01:56** remains pending until confirmation at **01:58**, then changes the score to 1–0. Longer fixtures and engineering tools are separate in Developer workspace.

## How it works

| Layer | Responsibility | Main source |
| --- | --- | --- |
| Synthetic source | Authored events, sampled positions, outcomes and provider corrections | `comparison-fixture.js`, `extended-fixture.js` |
| Received state | Replay clock, revision history, SSE updates and current inventory | `match-stream.js`, `stream-state.js` |
| Interpretation | Supported statistics, moment significance, bounded patterns and recap facts | `engine.js`, `moment-meaning.js`, `story-facts.js`, `recap-facts.js` |
| AI workflow | Natural question interpretation, typed operation proofs, bounded prose and editorial review | `match-question-ai.js`, `match-operation-proof.js`, `fact-workflow.js`, `recap-workflow.js` |
| Presentation | Watch view, persistent moment card and received-only animation | `stream-ui.js`, `fan-experience.js`, `pitch-motion.js`, `moment-replay.js` |
| Producer controls | Exact-evidence review, approvals, correction inbox and rundown export | `producer-review.js`, `producer-validation.js`, `producer-review-ui.js` |

Instant cards, animation and recorded recaps are deterministic. Open chat can generate reviewed prose from bounded queries. For supported numerical comparisons and ordered endpoints, AI instead selects a typed operation; the application computes and words its verified result, and a model reviews whether it answers the question. Provenance distinguishes application-rendered facts from model-written prose. Structured Studio workflows also select facts and render application templates. A model reviewer does not approve the producer's rundown. Intent interpretation and prose review remain fallible.

Animation interpolates received positional samples for display only. It does not supply analytical measurements, predict unseen positions or bridge fixture resets. Selected evidence scenes and buildup clips retain their own labeled times, separate from the current replay clock.

## Optional AI providers

Azure supplies the open match conversation. Historical timings and failures are retained in [development history](docs/DEVELOPMENT_HISTORY.md); provider status alone does not guarantee completion or answer quality. Local inference remains a separate experimental option.

### Local model on Windows

Install Python 3.10+, Node.js and Ollama, and start Ollama. Then run:

```powershell
powershell -File setup-local.ps1
npm run start:local
```

The setup installs locked Python dependencies and downloads `qwen3:4b`; it is separate from ordinary replay setup. The model is not included in the source archive. Microsoft Agent Framework invokes bounded read-only evidence tools through the local worker. CPU requests have taken over a minute in development. A working fresh-computer local AI setup remains to be verified.

`node check-setup.js --local-ai` checks the Python environment without invoking a model. `npm run probe:local -- --fact` intentionally runs local inference; it is not an installation prerequisite or part of the default tests.

### Azure model

For an authorized deployment, create an ignored `.env.azure` using the names in [.env.example](.env.example): `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` and `AZURE_OPENAI_API_KEY`. The adapter uses the v1 Chat Completions interface. The development integration uses a Microsoft Foundry deployment of GPT-4.1 mini with custom Node orchestration.

```sh
npm run start:azure
```

This command requires Node.js 20.6+ for `--env-file`. Use the address printed by the server; its port comes from private configuration. Keep keys on the server and outside the repository, browser code and distributed build.

The owner has authorized using the existing Azure trial credit for development and testing, with $0 cash and no pay-as-you-go upgrade. Preserve the configured request allowance and persistent ledger. `MODEL_BUDGET_FILE` retains reservations across restarts on the same filesystem; failed provider requests also consume reservations. A request counter is not a dollar cap. Do not reset it to bypass the allowance. An expiring trial is not a verified judging-period continuity plan.

The configured development allowance is 900 model-call reservations, expanded October 14 with the existing ledger preserved. An open question normally uses two or three calls; one optional evidence-repair cycle can add two, with a five-call maximum. Reservations persist across restarts; do not reset the ledger to bypass limits. Historical October 9 testing ended at 39 reservations. Normal UTC rollover does not change the overall trial-credit authorization. Documentation and default tests never authorize extra paid requests.

Public binding, access-token requirements and optional Docker operation are documented in [judge setup](docs/JUDGE_SETUP.md). The presence of Azure inference does not mean the website is hosted on Azure.

## Verify and package

These checks make no model calls:

```sh
npm test
npm run validate:data
npm run evaluate
npm run evaluate:recap
python -m unittest package_judge_test.py
python package_judge.py
python verify_judge_package.py
```

The Python packaging commands use the standard library and require Python 3.9+. Read [judge setup](docs/JUDGE_SETUP.md) for downloaded-archive verification and report options. The ZIP excludes credentials, installed dependencies, model weights and runtime budgets.

[GitHub verification](.github/workflows/verify.yml) prepares the same offline checks on Windows and Ubuntu with pinned actions, Node 24 and Python 3.12. It supplies no model credentials and performs no deployment. The workflow has been checked locally but has not run on GitHub yet.

The latest frozen release check, v30 on October 14, passed all eight gates with **1,027 passing Node checks and one optional skip (1,028 total)**. This includes actual Chrome layout and playback checks, packaging and isolated startup. Tests do not establish model accuracy or football realism. The last separate full extracted-ZIP test was v28; it does not certify subsequent changes. See docs/SUBMISSION.md for the current quality failures and delivery blockers.

## Scope and remaining validation

All teams and match data are fictional. The default is a short authored passage, not a full-match simulator or real Premier League footage. Supporting movement, ball flights and contact timing are schematic. Displayed sampled distances and displacement rates are not instantaneous speed, calibrated shot quality or tactical-causation estimates.

No independent fan sessions, native-language approval, full-match physics validation, production reliability study or demonstrated multi-agent advantage has been completed. Real participant testing is planned for the final stage close to submission. A clean extraction on this computer does not replace a second-computer test. A hosted judge URL, public repository, final recording and submission are not yet delivered.

No repository-wide license file has been selected. Do not assume that public availability grants reuse rights. Review dependency/model licenses and any third-party assets before release. This project uses fictional club identities and does not claim Premier League affiliation or rights to match footage.

## Project documents

- [Judge setup](docs/JUDGE_SETUP.md): current run and packaged-build instructions.
- [Submission pack](docs/SUBMISSION.md): pitch, rubric mapping, rules snapshot, evidence ledger and release checklist.
- [115-second demo script](docs/DEMO_SCRIPT.md): proposed recording sequence and verification gates.
- [Validation plan](docs/VALIDATION_PLAN.md): planned evaluations and dated development checkpoints.
- [Development history](docs/DEVELOPMENT_HISTORY.md): complete previous README, preserved without losing historical measurements or decisions. Its old walkthroughs and settings are superseded by this file.
- [Research record](docs/RESEARCH.md): earlier research and hypotheses, not current implementation claims.


Synthetic passing includes ground passes, lofted long balls, explicit crosses and outside-foot trivela passes in the wide-play family. Short/medium/long labels use authored endpoint distances (short at most 15m; long at least 25m); crosses and technique are explicit fixture attributes. Curves, height and shadows are illustrative authored animation, not calibrated football physics. The query engine includes saves and confirmed goals in shots on target, and ranks explicitly credited assists by the assisting player. The AI planner receives the full roster and latest action; its bounded recent evidence stays pinned to the submitted match time. Aggregate model packets retain counts and query references without duplicating full event lists.


Free-form questions now pin to the displayed replay second and do not inherit the automatic editorial highlight. The planner sees recent actions and roster identities; recipient filters distinguish intended passes from confirmed completions. Player zero-count queries include the eligible roster, and team comparisons include zero totals. A bounded graph of explicit received pass, shot and recovery links supplies historical buildup with current revisions, with repeated rows omitted from the model packet. These are retrieval and timing guarantees, not proof of live model answer quality.
