# Official brief and judging

[← Research](README.md)

Source authority: Microsoft’s [official rules](https://github.com/microsoft/insidethegamehackathon/blob/9c6c99620b06b2b04dcf69a434cdf4d203d19eda/OFFICIAL%20RULES.md), checked 13 October 2026. The pinned version makes this research reproducible; [current rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md) should be checked again before entering. The sections below paraphrase the rules.

## The required experience

Build a new AI solution using **synthetic, football-realistic events**, suitable for broadcast, studio, or streaming use. The brief describes five connected stages: ingest events; compute match context; explain significance; render alongside a match; adapt the experience to a viewer. It also calls for narratives and recaps. (§4.1, §4.7)

Player labels, speed/distance, pass quality, video-based event detection, and multilingual storytelling are suggested directions. They are not individually listed as mandatory features. Choose a few that support a coherent experience rather than trying to show everything. (§4.1)

## How it is judged

Microsoft selects the panel; the Premier League assists with final judging. Stage one is a fit/viability gate. Stage two has **five equal 20% weights**; ties are compared in criterion order, starting with technical implementation. (§2, §6)

![Equal judging weights](judging.svg)

| Criterion, simplified | Evidence we should show — our interpretation |
| --- | --- |
| Technical implementation — 20% | Original synthetic-data design, maintainable code, meaningful Microsoft integrations. |
| Agent design and innovation — 20% | A useful AI responsibility; clear tool boundaries, state, and recovery. |
| Real-world usefulness — 20% | A named user, a costly workflow problem, and a credible adoption path. |
| UX and presentation — 20% | An intuitive live experience and a concise demo showing the value. |
| Category fit — 20% | Explicitly demonstrate the selected category’s distinguishing behaviour. |

The rules name Foundry, Agent Framework, Azure MCP, Copilot agent mode, Fabric, GitHub tools, and Azure services as example hero technologies. The inspected version does **not** set a numeric “percentage of the stack must be Microsoft” threshold. (§6.2)

## Which category to target

| Category | What the rules emphasise | Our fit |
| --- | --- | --- |
| Overall first / second place | A complete, compelling use of the Microsoft AI stack with useful football experiences. | Keep all five scoring areas strong. |
| Microsoft Foundry | Development, orchestration, management, and scalable AI experiences. | Real model use plus evaluation and traces. |
| Enterprise solution | Reliability, transparency, controls, and a path to production. | Strongest provisional fit for a producer-facing tool. |
| Multi-agent system | Distinct roles, shared state, handoffs, recovery, and a better end-to-end result. | Use only if separate AI roles earn their complexity. |
| Azure cloud-native integration | Resilience, event-driven design, automation, and measurable business value. | A functioning hosted stream with recovery and instrumentation. |

Sources: §§4.2, 6.2. Category wording differs slightly between the category and prize tables; use the current submission form’s category labels. An entrant can win at most one grand prize and one category prize.

## Submission essentials

| Requirement | Implication |
| --- | --- |
| New work created after registration began | Existing libraries can support original work; copied competitor demos are not our entry. |
| Public GitHub code URL | This private research repo can stay private; prepare a separate, original public entry. |
| Working demo access | Provide a website, demo, or test build, free and available through the judging period. |
| Public video **under two minutes** | Show the real working project. The judges may rely on the video and description alone. |
| Pitch plus technology and problem description | Explain what was built, whom it helps, and the Microsoft/Azure components used. |
| English material or English translations | Include accessible testing instructions. |
| Rights to integrated software, data, footage, music, and branding | Original synthetic events and fictional teams are the cleanest demo foundation. |

Sources: §§4.3–4.11. Teams may have up to four people; eligibility exclusions and the full entry terms still apply. No entry or acceptance of terms has been performed.

## Dates in Brisbane

| Milestone | Australia/Brisbane | Source time |
| --- | --- | --- |
| Registration began | 30 September 2026, 2 am | 29 September, 9 am Pacific |
| Registration closes | **21 October 2026, 5 am** | 20 October, noon Pacific |
| Submit by | **28 October 2026, 4:59 pm** | 27 October, 11:59 pm Pacific |
| Keep demo available until judging ends | **11 November 2026, 5:59 pm** | 10 November, 11:59 pm Pacific |

Source: §1; conversion uses Los Angeles daylight-saving rules. Finish the entry before the deadline rather than depending on the last minute.

## Recommended proof to put in a 110-second demo

This is our proposal, not an official video template.

| Seconds | Show |
| --- | --- |
| 0–15 | The producer’s problem and a fictional match starting. |
| 15–40 | A meaningful change detected, its explanation, and clickable supporting events. |
| 40–60 | The same facts shown differently to a casual fan and an analyst. |
| 60–80 | A corrected/missing event; the system updates or withdraws the affected claim. |
| 80–100 | The publish control, trace, measured latency, and one scenario-quality result. |
| 100–110 | Who would adopt it and the selected category. |

Microsoft’s [hackathon Reactor series](https://developer.microsoft.com/en-us/reactor/series/S-1709/) is a useful implementation reference. Its currently listed AKS/Container Apps session is **15 October, 2–3 am Brisbane** (14 October, 16:00–17:00 UTC); a replay may be more practical.
