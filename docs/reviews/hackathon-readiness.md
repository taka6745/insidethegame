# Hackathon readiness

Reviewed **19 October 2026** against the [current official rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md), the detailed Excalidraw board and active service contracts. **Working local demo; no production capacity or Azure deployment claim.** This review does not certify eligibility or predict judging results.

## Brief and implementation

| Area | Built and inspectable | Remaining boundary |
|---|---|---|
| Ingest / interpret | Aligned GRF recording; ETL-owned history, measured possession and standard stats through GraphQL. [ETL](../../etl/README.md) | Local PostgreSQL substitutes for Azure SQL/Cosmos. ASA and production event ingestion are teammate-owned work. |
| Explain / recap | Grounded question agent; neutral recap tiers with retained children. [Question tools](../../user-backend/backend/agents/question.py) | Narrative stub uses factual summaries and offline AI-authored versions (92 minutes × 12 buckets, tier recaps, key moments). This is not evidence of live AI narrative generation. Chat replay clips are built by a replay agent over these and the raw events. |
| Render / personalize | Video, five live cards, 12 audience combinations, optional custom-stat tracking. [Viewer](../../frontend/README.md) | English-only demo; internationalization is not demonstrated. |
| Purposeful agents | Actual Microsoft Agent Framework agents and workflow, clarification, validated DSL compilation and bounded repairs. [Workflow](../../user-backend/backend/agents/workflow.py) | Fresh setup defaults to fixture doubles. Configure model mode to demonstrate flexible questions. Arbitrary Python execution is deferred. |
| Microsoft / Azure | Azure SDK broker adapters, Docker services, Microsoft emulator checks and Terraform foundation. [Local setup](../../local/README.md) | Foundry/cloud application deployment and durable production recovery/coordination remain unimplemented. LocalStack Azure is not installed. |

The [five-stage brief (§4.1)](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md#41-hackathon-challenge) concerns ingestion, interpretation, explanation, rendering and personalization. Describe the authored narratives as fixtures while demonstrating the implemented question and custom-stat intelligence.

## Judging evidence

The [five criteria (§6)](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md#6-judges--criteria) each carry 20%.

| Criterion | Current strength | Evidence still needed |
|---|---|---|
| Technical implementation | Isolated service ownership, validated rules, unavailable-data handling, live updates. | Repeatable fresh-machine run, real model trace and failure/reconnect demonstration. Test counts belong in dated verification records. |
| Agentic design | Goal interpretation, clarification, tool-based evidence retrieval and deterministic compilation have distinct jobs. | Show the handoff and repair trace. Do not call the deterministic compiler another autonomous model. |
| Real-world impact | Shared calculations and bucket narratives avoid a model loop for every watching viewer. | End-to-end fan-out, question-load and recovery tests; production authentication and ownership. |
| UX / presentation | Stream-first match view, short answers and live Track cards. | Concise working walkthrough with fixture/provenance disclosure. |
| Category fit | Microsoft Agent Framework integration is present in executable code. | Foundry/cloud-native categories need actual integrations; enterprise readiness needs operational evidence. |

[Scaling design](../../user-backend/docs/scaling.md) separates filter-algorithm measurements from viewer capacity. One local process owns replay and live sessions. Static assets can be distributed independently, but adding API replicas does not make the current state distributed.

## Short demonstration recipe

1. Follow [local model setup](../../user-backend/docs/local-llm.md) using ignored configuration. Start `./dev up backend`; confirm model mode in the lab. Fixture mode only recognizes documented samples and must not be presented as flexible AI.
2. Reset and start the shared match. Show aligned footage if available, then switch audience to compare the same moment's authored framing. Explicitly identify the synthetic match and authored narrative fixture.
3. Ask for a supported ETL statistic, then a custom scope such as **Chelsea's completed passes since minute 5** after that point. Show the short answer, Track action and changing card. The 90-minute recording (Chelsea 2–1 Manchester United) has 6 corners taken, 4 cards (one second-yellow red) and headed passes, shots and clearances. Then ask for a replay such as **show me all the shots so far**. Ask specifically for headed passes rather than ambiguous “headers”; not every headed action is measured.
4. Show clarification and unsupported-data behavior, then reconnect to demonstrate restored state. Keep model traces and measured timings as evidence, not screen clutter.

The [current recording](../../data-generation/recordings/README.md), [narrative fixture](../../narrative-engine/fixtures/README.md) and [frontend verification](../../frontend/docs/verification.md) document the actual demo, separate from planned services.

## Submission gates

These are open delivery checks, not reasons to expand the approved stub implementation:

- Confirm entrant/team eligibility, registration and project dates against the official rules; repository inspection cannot establish these.
- Provide a public repository, functioning judging access and an English demonstration **under two minutes**; keep access available throughout judging. Localhost and ignored local model/video files are not judge access.
- Record permission for third-party fonts, crests, logos and media, or use cleared substitutes. [Asset provenance](../../frontend/assets/league/PROVENANCE.md) is attribution, not permission. [Rules §§4.4–4.8](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md#44-submission-requirements) govern submitted materials and access.
- Disclose synthetic data, illustrative player identities and authored narratives. Keep the requested branding/layout intact during development; resolve release rights before submission.
- Demonstrate only the deployed platform and features that actually work. A Terraform validation or emulator probe does not demonstrate cloud application deployment.

The user backend still owns audiences, questions, pins and custom rules. ETL owns standard stats/history; the narrative service owns framing and recaps. Questions do not start shared narrative authoring. Production upstream replacement should preserve those boundaries.
