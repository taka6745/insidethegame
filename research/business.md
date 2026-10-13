# Business context

[← Research](README.md) · [Existing products](landscape.md)

## Is this idea-sourcing?

**Working hypothesis: a low-cost way to surface useful prototypes and research for the Microsoft–Premier League programme.** We should assess the entry as an idea someone could extend internally, without expecting the organisers to announce that intent.

| Evidence | What it supports | What it cannot establish |
| --- | --- | --- |
| A five-year Cloud & AI partnership spanning fan experiences, match analysis, Azure infrastructure, and internal operations. | There are real product programmes a prototype could serve. | That this hackathon has an allocated procurement budget. |
| The brief targets synthetic event intelligence, broadcasting, and enterprise-capable Microsoft AI. | Directed experimentation around partnership-relevant problems. | Which internal team would adopt a winner. |
| Cash-equivalent prizes are $4,000 per first-place member, $2,500 per second-place member, and $1,500 per category winner, paid as e-gift cards. | A prize-led prototype exercise, rather than disclosed implementation funding. “Modest” is our assessment relative to a production build. | Microsoft’s staffing cost or the full effort behind the programme. |
| Entrants retain ownership, while the organisers receive broad, perpetual, non-exclusive commercial-use rights. | The organisers can reuse submissions commercially without a later purchase commitment. | A plan to copy any particular entrant’s idea or a transfer of ownership. |
| Winner social promotion is explicitly included. | Visibility is one programme benefit. | That marketing is the principal purpose. |

The partnership facts come from the [joint announcement](https://news.microsoft.com/source/2025/07/01/premier-league-and-microsoft-announce-five-year-strategic-partnership-to-personalize-the-fan-experience-with-ai-for-1-8-billion-people/). Prize and reuse facts come from [rules §§7–8](https://github.com/microsoft/insidethegamehackathon/blob/9c6c99620b06b2b04dcf69a434cdf4d203d19eda/OFFICIAL%20RULES.md#7-intellectual-property-rights). The first-place package also includes a ticket and store voucher; cash figures alone are not total prize value.

**Our inference:** idea-sourcing is credible and useful as a design lens. A strong entry should make one valuable capability easy to evaluate and extend. The documents establish no investment, hiring, deployment, or buying obligation. The user’s impression of low organiser effort is a hypothesis; public pages do not quantify internal effort.

## Who controls what?

| Organisation / team | Relevant responsibility | A useful prototype could help with |
| --- | --- | --- |
| Premier League | Runs the competition and league rules, distributes central revenues, and sells central broadcast rights. | Consistent match information and partner-ready content across the competition. |
| Premier League Studios | International content production and distribution, brought in-house for 2026/27. | Finding and explaining stories, producer approval, reusable output for markets. |
| Premier League digital products | App, website, Companion, FPL, and the Singapore PL+ service. | Clearer personalised match experiences within existing products. |
| Broadcasters / regional partners | Local presentation and distribution under their rights arrangements. | Localisation, feed timing, graphics integration, and editorial control. |
| Individual clubs | Independent organisations with their own football and commercial operations. | Recruitment/coaching products usually need club-specific buyers and data. |
| Microsoft | Cloud/AI platform and organisational-technology partner; selects the hackathon judges. | A credible, reproducible workload that uses its platform well and can be operationalised. |
| Data / graphics suppliers | Tracking, event feeds, visualisation, and specialist integrations. | Adapters and validated evidence packets, rather than assuming access to their proprietary feeds. |

League/club scope: [governance](https://www.premierleague.com/en/news/4679198/4322439). Media production: [in-house announcement](https://www.premierleague.com/es/news/4172032). Current distribution examples: [PL+ launch](https://www.premierleague.com/en/news/4687725/premier-league-launches-video-streaming-service-in-singapore) and [broadcast rights](https://www.premierleague.com/es/news/3703577/premier-league-broadcast-deals-for-2025-2028). Microsoft scope: [partnership](https://www.premierleague.com/en/about/partners/microsoft) and [rules §2](https://github.com/microsoft/insidethegamehackathon/blob/9c6c99620b06b2b04dcf69a434cdf4d203d19eda/OFFICIAL%20RULES.md#2-promotion-entities-and-administrator).

This makes a production/fan-experience prototype a closer route to the published challenge than a club recruitment tool. That is a fit assessment, not a claim that recruitment research has no value.

## What might matter to Microsoft’s judges?

Our interpretation of the published rubric and partnership:

| Question they can assess | What we can demonstrate |
| --- | --- |
| Could a partner use this capability? | A specific producer task and a clear connection to an existing feed/UI. |
| Does the Microsoft platform do something substantive? | A real Foundry model call, a purposeful workflow, traceability, and a hosted endpoint. |
| Is the AI contribution useful and different? | Fewer unsupported stories, better recovery, or a new way of evaluating synthetic match narratives. |
| Can this move beyond a stage demo? | Versioned event contracts, repeatable scenarios, sensible fallbacks, and measured operating behaviour. |
| Can they understand it immediately? | A polished producer/fan experience that works in a short video. |

The [rubric](brief.md#how-it-is-judged) still gives UX and category fit the same weight as technical quality. A commercially sensible backend needs an understandable front end.

## Candidate directions

These are research proposals, not validated demand or implementation commitments.

| Candidate | What a person gets | Adoption hypothesis | Key risk | Recommendation |
| --- | --- | --- | --- | --- |
| **Live story desk + correction handling** | A producer gets an explanation, evidence, audience versions, and publish/retract controls. | A component for Studios, broadcast partners, or the existing fan platforms. | Many entrants already claim evidence-backed stories; our failure/recovery behaviour must be visibly better. | **Provisional first choice.** |
| **Synthetic story robustness lab** | A producer/researcher compares stories under noisy, corrected, and subtly different match scenarios. | An evaluation harness an internal team could use while building match AI. | It can become a backend-only test tool; still demonstrate a live viewer output and the full brief. | Build a small part of this into the first choice. |
| **Explainable accessible audio** | A blind fan hears spatial context and can ask what changed. | An accessible viewing mode inside a partner product. | Several entrants already propose it; spatial clarity and user validation matter more than generic TTS. | Strong alternative if we can test with users. |
| **Video-to-events with a new vision model** | A producer gets tracked players or candidate events from video. | An ingestion capability for content teams. | Existing tracking suppliers are advanced; identity, speed calibration, rights, and compute increase delivery risk. | A bounded experiment, not the core two-week plan. |

## How we would prove business value

Use a small before/after task: “find a defensible story for this minute, prepare a fan version, then handle a feed correction.” Measure **producer review time**, **unsupported claims**, **correction delay**, **event-to-card latency**, and **cost per accepted story**. Define “accepted” before testing; a language model judging itself is insufficient.

Illustrative sizing only: 380 matches × 5 stories × 20 language/market versions × 3 minutes of manual work = **1,900 hours**. Halving that work would save **950 hours**. The volume, markets, review time, and saving are assumptions to validate with a production team—not known Premier League staffing figures. The 380-match season is documented in the [PL+ announcement](https://www.premierleague.com/en/news/4687725/premier-league-launches-video-streaming-service-in-singapore).

The strongest value claim would be measured on our prototype. Revenue uplift, actual labour savings, rights availability, and buying interest remain unverified. A win or a broad reuse licence is not a customer contract.
