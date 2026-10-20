# Match experience references

Research checked 18 October 2026. The user requested a Premier League integration prototype: authentic league typography, club crests and match-centre conventions, with a discreet hackathon/unofficial-product footer. It is not an official released Premier League product.

| Reference | What we take from it |
|---|---|
| [Premier League match centre](https://www.premierleague.com/en/matches) | Establish the teams, match clock and score before asking the viewer to interpret statistics. |
| [Premier League and Microsoft](https://www.premierleague.com/en/about/partners/microsoft) | Personalised insights can accompany football viewing. Our demo separates shared bucket narratives from direct questions and explicitly tracked statistics. |
| [Fluent accessibility](https://fluent2.microsoft.design/accessibility) | Visible keyboard focus, descriptive controls, readable contrast and statuses that do not rely on colour alone. |
| [Fluent motion](https://fluent2.microsoft.design/motion) | Motion communicates changed state; reduced-motion users receive the same information without animation. |
| [Azure Web PubSub performance](https://learn.microsoft.com/en-us/azure/azure-web-pubsub/concept-performance) | Capacity depends on message size, frequency and fan-out, not simply the number of open connections. |
| [Azure reliable clients](https://learn.microsoft.com/en-us/azure/azure-web-pubsub/howto-develop-reliable-clients) | A cloud adapter should use the supported SDK recovery protocol; the local WebSocket transport is not an implementation of that protocol. |
| [Hackathon rules](https://github.com/microsoft/insidethegamehackathon/blob/main/OFFICIAL%20RULES.md) | Demonstrate synthetic data, a responsive viewing experience, personalisation and purposeful agents. Describe planned production capabilities honestly. |

## Visual direction

The current official match centre uses deep purple surfaces, PremierLeague W01 typography, club crests, team-colour match banners and a compact score panel. The prototype follows that language, adding Inside the Game as a match-centre feature. Chelsea/Manchester United banners use authentic crests over CSS club-colour surfaces. The main area shows an optional 90-minute synthetic GRF recording (live HLS) whose video and ETL events share the same timeline. Player names map illustrative simulator slots, not measured real-player abilities. Without a source, it shows an explicit unavailable state. Five compact statistics sit below it. Raw events stay in the developer lab.

The compact desktop layout keeps the player and five stat slots in view while the companion history scrolls internally. On mobile the stat row scrolls horizontally and the companion follows the player. Insight and question tabs have different purposes: ongoing bucket narratives versus a personal conversation. Three generated feature icons are rebuilt as small native SVGs; [provenance and comparison](../assets/README.md) are retained separately from shipped assets. Official fonts and marks have separate [source attribution](../assets/league/PROVENANCE.md); those are authentic third-party files, not generated substitutes.

## Acceptance

- One coherent match/run across score, cards, narratives, events and question context.
- Profile resolves the audience; custom tracking replaces the lowest-priority default slot.
- Questions preserve their as-of snapshot. Live cards continue advancing independently.
- Mid-match join and reconnect restore current state and backlog; a second session visibly takes over.
- Missing data, loading, disconnects and agent failures are visible. No fabricated fallback statistics.
- Keyboard/mobile layouts, reduced motion, bounded feed/history and text-only untrusted content.
- Static assets can be served independently; one push connection per viewer, shared upstream work per match, no per-viewer model loop.

These are acceptance requirements, not evidence that all production integrations or viewer capacity have been tested. Record actual validation in the development guide.

## Companion styling

The official [Premier League Companion](https://www.premierleague.com/en/news/4345260/what-is-the-premier-league-companion/) was inspected on 18 October 2026, including its public entry panel and `v1.54.15` stylesheet. Observed patterns: white selected segmented tabs, outlined pill prompts, a rounded bottom composer, purple surfaces, colour-edged loading, staggered prompt fades and response entrance animation. No question was sent to the official service.

Our implementation uses those patterns in `match/companion.css`, with the existing PL typeface and our original feature icon. It keeps the truthful Microsoft Agent Framework credit rather than claiming the prototype is powered by Copilot. Motion is CSS-only, disabled when reduced motion is requested, and does not delay answers. Only a pending answer becoming ready gets a reveal; restored history and pin updates do not restart it. Live match frames do not drive animation or model calls.
