# New technology we could actually use

[← Research](README.md)

Checked **13 October 2026**. Recent release dates below come from the maintainer’s own release records, not popularity rankings. A release tag is evidence of publication, not proof that it works in our environment.

| Technology | What is recent / confirmed | What it could improve | Decision |
| --- | --- | --- | --- |
| [Microsoft Agent Framework Python 1.21.0](https://github.com/microsoft/agent-framework/releases/tag/python-1.21.0) | Released **8 October 2026**. Recent work includes streamed-response policy handling and provider session isolation. | A Microsoft-native story workflow with controlled tools, state, and recoverable handoffs. | **Best core candidate.** Pin the version and validate our chosen provider and APIs. |
| [AG-UI integration](https://learn.microsoft.com/en-us/agent-framework/integrations/ag-ui/) | Official Agent Framework integration for streamed agent state and interactive clients. Some SDK integration packages still use prerelease installation paths. | Show a story being considered, the evidence returned by tools, and a producer’s approval in the same UI. | **Useful if it reduces custom wiring.** It is not the broadcast overlay renderer by itself. |
| [A2UI Python agent SDK 0.8.0](https://github.com/a2ui-project/a2ui/releases/tag/python/a2ui-agent-sdk/v0.8.0) | Released **8 October 2026**, with schema/catalog and validation changes. Documentation lists protocol 0.9.1 as current and 1.0 as a candidate. | Allowlisted, declarative evidence cards and controls that adapt to a viewer without generating executable UI code. | **One small experiment.** Recent breaking changes and protocol/package version differences make a big rewrite risky. |
| [SAM 3.1](https://ai.meta.com/blog/segment-anything-model-3/) | Meta’s **27 March 2026** update improves multi-object video tracking through multiplexing. | A bounded demo tracking players in our own synthetic rendered clip. | **Optional research feature.** Segmentation does not identify real players or turn pixels into calibrated pass/shot speeds automatically. Benchmark our clip and hardware. |
| [Foundry Local](https://learn.microsoft.com/en-us/azure/foundry-local/what-is-foundry-local) | Device-runtime documentation updated **4 August 2026**; supports local inference and multiple SDK languages. | A local commentary fallback, privacy-sensitive producer preview, or offline demonstration. | **Optional fallback.** Confirm model quality and platform support; this does not replace demonstrated cloud integration if that is our category. |
| [Foundry Local on Azure Local](https://learn.microsoft.com/en-us/azure/azure-sovereign-clouds/private/foundry-local/whats-new) | **September 2026** preview update adds Kubernetes service-account authentication; prior updates cover local evaluation and multi-GPU serving. | A later private/edge production deployment path. | **Too much infrastructure for the first prototype.** This cluster product differs from the device runtime above. |
| [Fabric Real-Time Intelligence](https://learn.microsoft.com/en-gb/fabric/real-time-intelligence/) / [Digital Twin Builder](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/digital-twin-builder/tutorial-0-introduction) | Streaming platform plus a documented **preview** for operational twin modelling. | Model matches, players, and event relationships; inspect time-series changes. | **Use only if the data model needs it.** An operational twin preview is not a ready-made football simulator. |

The [A2UI specification](https://github.com/a2ui-project/a2ui/blob/main/docs/public/index.md) and [renderer matrix](https://github.com/a2ui-project/a2ui/blob/main/docs/public/reference/renderers.md) must be checked together. A2UI is an interface-description format; AG-UI is an agent/client event protocol; MCP exposes tools; A2A connects agents. These roles are complementary, but using all four does not itself create a better product.

## A small stack worth testing

Proposed implementation, not installed or benchmarked here:

| Responsibility | First choice |
| --- | --- |
| Original event generator, replay, statistics, and validation | Small deterministic code with a stable event schema. |
| Story selection / wording | Microsoft Foundry model behind Agent Framework, with a constrained fact packet. |
| Producer and fan interface | A few reusable cards, a pitch/timeline, evidence links, and audience controls. |
| Streaming / approval state | AG-UI if a quick spike proves it simpler; otherwise a direct event stream. |
| Hosted demo | Azure Container Apps, matching the hackathon’s [deployment learning session](https://developer.microsoft.com/en-us/reactor/series/S-1709/). |
| Quality evidence | Repeatable synthetic scenarios; measured claim validity, latency, correction delay, and review time. |

Start with **one recent integration** that is visible in the demo. Keep a direct renderer and template fallback so SDK churn cannot break the entry. Use a purposeful second AI agent only if it demonstrably improves the outcome; analytics and rule validation remain ordinary code.

## Quick adoption tests

| Candidate | Pass condition before committing to it |
| --- | --- |
| Agent Framework + Foundry | Stream one evidence-grounded story and recover cleanly from a failed model/tool call. |
| AG-UI / A2UI | Render one allowlisted evidence card, process an approval, and update it after a corrected event. Reject malformed output. |
| SAM 3.1 | Track objects on a short original rendered clip and measure identity continuity and latency on our hardware. |
| Foundry Local | Produce an acceptable constrained explanation offline on the actual demo machine. |
| Fabric | Demonstrate a useful query/relationship that our simple event model cannot serve as clearly. |

No current prices, account quotas, model access, deployment regions, or latency claims have been assumed. Verify those against the actual account when we select and build the entry. Novelty should be in the useful behaviour and evidence, not the number of new SDK names.
