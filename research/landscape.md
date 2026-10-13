# What already exists?

[← Research](README.md) · [Collected competitor data](../competitors/README.md#their-data)

Primary product/league sources checked 13 October 2026. Features below are documented by the organisations; performance and sales claims have not been independently benchmarked.

| Existing product / programme | Documented capability | Implication for our entry |
| --- | --- | --- |
| [Premier League Companion](https://www.premierleague.com/en/about/partners/microsoft) | Personalised access to league statistics and content; overlays, multilingual support, and FPL features are described in the partnership. | “Chat about football” is already part of the programme. Distinguish launched features from announced additions. |
| [Premier League +](https://www.premierleague.com/en/news/4687725/premier-league-launches-video-streaming-service-in-singapore), launched 12 August 2026 | Singapore streaming service with multi-camera viewing, live overlays, club hubs, and Studios programming. | A real surface already exists for richer match experiences. It is region-specific, not evidence of a global direct service. |
| [Opta Vision](https://www.statsperform.com/products/opta-vision/) | Synchronised player tracking and events, team shape, pressure and off-ball analysis. | Tracking and advanced statistics are established supplier capabilities; our synthetic demo cannot claim equivalent professional accuracy. |
| [Genius Sports](https://www.geniussports.com/content-hub/how-ai-transforms-the-live-sports-experience/) | Tracking, event interpretation, and synchronised data/graphics augmentation. | Player IDs, mini-maps and data overlays alone are not new. |
| [Viz Libero](https://www.vizrt.com/products/viz-libero/) | Sports analysis graphics, telestration, 3D views, and data integration. | A credible future product should produce an integration-friendly story packet or graphic, not need to replace a production suite. |
| [WSC Sports](https://wsc-sports.com/blog/news/how-the-cleveland-cavaliers-are-building-a-scalable-fan-experience-with-genai/), March 2026 example | Personalised in-app content and generative-AI-assisted narrated assets. | Automated highlights and personalisation are established capabilities, including outside football. |
| [Bundesliga Data Story Finder](https://aws.amazon.com/blogs/media/bundesliga-data-story-finder-delivering-fans-the-stories-they-love/) | Finds story opportunities from match data for editorial teams. | “AI finds the match story” already has an operational analogue on another cloud. |

The League’s [semi-automated offside system](https://www.premierleague.com/ar/news/4273447), introduced in April 2025 with PGMOL and Genius Sports, also shows that officiating/tracking systems have specialist partnerships. A hackathon prototype should be precise about which part of that chain it addresses.

## What our competitors already claim

The local [121-project snapshot](../competitors/data/projects.json) includes many variations on commentary, verified narratives, personalised feeds, and overlays. We have inspected **18 readable repos** and collected **40 files from 10 repos**. The [repo table](../competitors/README.md#repositories) distinguishes working-source claims, generators, sample files, and planning entries.

| Repeated idea | Examples in our snapshot | A narrower experiment worth testing |
| --- | --- | --- |
| Evidence-backed broadcast stories | The Gallery, Pitch Ledger, Virtual Studio Crew | What happens after a supporting event is corrected or withdrawn? |
| Multilingual / personalised commentary | MatchMind Broadcast Booth, Matchday Crew, Msimulizi | Does the same underlying evidence survive translation and simplification? |
| Pressure / momentum explanations | Shift11, Control vs. Chaos, MatchLens | Can the system distinguish a meaningful designed change from a noisy short run? |
| Accessible audio | Audio Eyes, Blind-side, Sauti, VYBE | Can a user locate play and understand a turning point better than with plain commentary? |
| What-if and coaching | ReactCoach 11, Second Guess, Half-Time Lab | Are assumptions visible, and can the user see how sensitive the result is? |
| Data-format conversion | VendorIQ | Can inconsistent/corrected inputs preserve the meaning of downstream claims? |

These gaps are **proposed tests**, not proven vacant markets. We have not audited every commercial system or every unavailable competitor repository. A precise comparison and measured behaviour are stronger than claiming a feature is unique.

## The useful gap to pursue

Our current bet is the step between “the data says something” and “a producer can safely put this explanation on screen.” Make confidence, evidence, timing, corrections, and audience adaptation visible in one simple workflow. Pair it with original synthetic cases whose designed structure lets us test the explanation quality.

Validate novelty before implementation: read the nearest entrants’ producer, verification, and event-replay code; compare correction semantics and evaluation coverage; then choose one behaviour we can demonstrate better. The collected data helps research those patterns, but our entry should use original synthetic events.
