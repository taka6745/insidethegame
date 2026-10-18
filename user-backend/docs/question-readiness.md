# Question-agent readiness

**18 October 2026 — local implementation, not a production-readiness declaration.** This page separates the implemented slice from evidence still needed for a complete hackathon entry. Test coverage is listed in [testing.md](testing.md).

## Checked in this change

- **375 backend tests** and **27 frontend tests** passed. The separate Docker replay and filter-lab smoke checks passed.
- Independent reviews covered the full backend's service boundaries, agents, adapters, persistence, indexing and delivery. Findings were fixed; a fresh final reviewer found no further actionable issue and passed 84 focused tests.
- The ten-case [live conversation check](../benchmarks/question_cases.json) passed its automatic checks. Manual inspection confirmed standard shots **5**, custom headed shots **3**, second-half follow-up **2**, all headed contacts **6**, and corners strictly after 60:00 **5**, including the generated predicates. Asking alone registered no live calculation.
- The same run exercised clarification, historical drill-down including the exact end timestamp, a rules explanation and unavailable data. Observed response times were **2.31–17.53 seconds**, median **10.21 seconds**; one sequential local run, not a throughput benchmark. Natural-language quality remains model-dependent; this is not a general accuracy score.
- Browser verification: a before-kickoff answer stayed at **0**, while selecting Track and replaying the recording updated its live metric to **3**. The conversation, Tracking state and live value survived refresh.

The API entry point now composes routes/services. Viewer operations and live queues have separate modules; bucket delivery shares upstream reads and has bounded retry state. No arbitrary generated code, extra deployment layer or per-viewer narrative workflow was added.

| Area | Implemented / available evidence | Still to demonstrate or integrate |
|---|---|---|
| Match questions | Microsoft Agent Framework tools; snapshot-bound GraphQL adapters; persistent chat and clarification | Repeatable live-model accuracy and response-time evaluation across good, ambiguous and unsupported requests |
| Custom statistics | Validated rule workflow, exact one-off result, explicit Track, shared indexed calculation | Per-viewer card replacement and production event/history handoff |
| Recap memory | Synthetic neutral minute/five-minute/earlier blocks, archived children and drill-down tests | Real narrative-engine GraphQL contract, shared LLM summaries and bucket authoring |
| Microsoft services | SDK in running application; optional Service Bus adapter; Docker/emulator and Terraform checks | Actual Foundry/Azure deployment evidence if claiming those integrations |
| Scale | Filter correctness tests and [measured algorithm benchmarks](../benchmarks/results/README.md) | Concurrent question capacity, model/token cost, database load, delivery fan-out and multi-replica recovery |

A filter lookup benchmark does **not** establish a viewer-capacity figure. The current lab has one process, one shared replay and local polling. Its snapshot bridge and fake upstreams are test infrastructure. Keep those labels in demonstrations.

## Judging evidence to prepare

The [official Microsoft rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md), checked **18 October 2026**, give equal weight to technical implementation, agent design, real-world impact, UX/presentation and category fit (§6). The enterprise category asks for a credible adoption path with reliability and controls; it does not turn algorithm timings into enterprise readiness (§4.2).

| Evidence | Useful demonstration |
|---|---|
| End-to-end value | Ask a match question, clarify “headers”, get a verified stat, select Track and watch a later event update it |
| Purposeful agents | Show the question-agent tool call and goal/compiler validation handoff, including a clarification or recoverable failure |
| Personalisation | Show actual different audience experiences; catalogue definitions alone are not the finished feature |
| Transparency | Show the as-of label, a supporting recap/event reference, and a short refusal for missing data |

## Submission gates — separate from implementation fixes

Recheck [rules §§4.3–4.9](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md) before submitting:

- Public GitHub repository and working judge-accessible demo/test build, available through judging.
- Public working-demo video under two minutes; English materials or translations.
- Synthetic data provenance and necessary third-party permissions.
- Pitch and category claims match the demonstrated implementation. Local fixtures, diagrams and planned cloud services remain labelled.

This page does not verify registration, eligibility, submission, public access or cloud deployment.
