# Design references

> **In short:** the fictional Elephant League viewer was inspired by real-world references checked on 18 October 2026: the Premier League's match centre and Companion, Microsoft's Fluent guidance and Azure delivery guidance. No real league's fonts, marks or crests are used.

| | |
| --- | --- |
| **Status** | Design material, not updated |
| **Checked** | 18 October 2026 |

## 1. References

*In short: what each real-world reference taught the design.*

| Reference | What we took from it |
|---|---|
| [Premier League match centre](https://www.premierleague.com/en/matches) | Establish the teams, match clock and score before asking the viewer to interpret statistics. |
| [Premier League and Microsoft](https://www.premierleague.com/en/about/partners/microsoft) | Personalised insights can accompany football viewing. Our demo separates shared bucket narratives from direct questions and explicitly tracked statistics. |
| [Premier League Companion](https://www.premierleague.com/en/news/4345260/what-is-the-premier-league-companion/) | Selected segmented tabs, outlined pill prompts, a rounded bottom composer, colour-edged loading and a response entrance animation. Inspected from its public entry panel and stylesheet; no question was sent. |
| [Fluent accessibility](https://fluent2.microsoft.design/accessibility) | Visible keyboard focus, descriptive controls, readable contrast and statuses that do not rely on colour alone. |
| [Fluent motion](https://fluent2.microsoft.design/motion) | Motion communicates changed state; reduced-motion users receive the same information without animation. |
| [Azure Web PubSub performance](https://learn.microsoft.com/en-us/azure/azure-web-pubsub/concept-performance) | Capacity depends on message size, frequency and fan-out, not simply the number of open connections. |
| [Azure reliable clients](https://learn.microsoft.com/en-us/azure/azure-web-pubsub/howto-develop-reliable-clients) | A cloud adapter should use the supported SDK recovery protocol; the local WebSocket transport is not an implementation of that protocol. |
| [Hackathon rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md) | Demonstrate synthetic data, a responsive viewing experience, personalisation and purposeful agents. Describe planned production capabilities honestly. |

## 2. Visual direction

*In short: a match-centre layout for a league that does not exist.*

Deep surfaces, team-colour banners and a compact score panel frame the match; club colours and the original crests come from the match data. The footage is a synthetic simulation whose video and events share one timeline; five compact statistics sit below it, raw events stay in the lab. On desktop the player and stat slots stay in view while the companion scrolls; on mobile the companion follows the player. Insights (shared narratives) and questions (a personal conversation) are separate tabs. Companion motion is CSS-only, off under reduced motion, and never delays answers; only a pending answer becoming ready gets a reveal. The footer keeps the truthful Microsoft Agent Framework credit and a hackathon-demo note.

## 3. Acceptance

*In short: requirements, not evidence of production capacity.*

- One coherent match across score, cards, narratives, events and question context.
- Profile resolves the audience; custom tracking replaces the lowest-priority default slot.
- Questions keep their as-of snapshot; live cards keep advancing.
- Mid-match join and reconnect restore current state and backlog; a second session visibly takes over.
- Missing data, loading, disconnects and agent failures are visible. No fabricated fallback statistics.
- Keyboard and mobile layouts, reduced motion, bounded feed and history, text-only untrusted content.
- Static assets served independently; one push connection per viewer, shared upstream work per match, no per-viewer model loop.
