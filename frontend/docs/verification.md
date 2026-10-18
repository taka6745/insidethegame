# Viewer verification

Latest aligned GRF, upstream-service and question/pinning checks verified locally on 19 October 2026. Earlier visual and icon checks are retained below. This is a synthetic demonstration, not a real fixture or a production capacity certification.

| Check | Result |
|---|---|
| Backend regression suite | 428 passed; one existing Starlette/httpx deprecation warning |
| Frontend unit/contract tests | 77 passed |
| Native SVG harness tests | 6 passed; all three icons exceed 80% foreground overlap |
| Separate-service check | GRF checkpoints at 0, 1, 6 and 12 video minutes: ETL history/stats and narrative recap coverage agree |
| Upstream/generator tests | 14 ETL (including real PostgreSQL), 26 narrative, 12 generator tests passed |
| Independent agent review | Fresh review clean after fixes; final setup delta also reviewed clean |

Browser checks covered the actual Docker-served viewer: Chelsea–United marks/fonts, live score and standard cards, profile switching, question answers, Track/Untrack, saved chat/pins on refresh, session takeover and narrow layout. A pre-match headed-shot answer stayed at zero while its tracked live card reached three. Restarting the backend mid-replay reconnected without a page reload, exposed Resume match and continued from the saved position. No browser console errors were observed.

`node frontend/benchmarks/client.mjs` passed: 78,933 gzip bytes for all shipped UI/assets (including fonts/marks); UI code alone 19,163 gzip bytes. Ten thousand bounded state replacements took 2.78 ms in this run. This is a local reducer measurement, **not** DOM rendering, delivery latency or concurrent-viewer capacity. Rerun on the target environment rather than treating the timing as a guarantee.

[Live contract and production boundaries](live-contract.md) · [Icon evidence](../assets/README.md) · [Brand asset provenance](../assets/league/PROVENANCE.md)

Companion styling follow-up: public PL Companion UI/CSS inspected; CSS-only prompt/loading/answer motion added with reduced-motion opt-out. Regression checks cover pending-to-complete identity and avoid reanimating restored answers or pin updates. Independent follow-up review clean.

Stream-first follow-up: five ETL-owned stat slots, raw events confined to the lab, compact scorebar and internally scrolling companion. Browser checks confirmed simulator playback, Pause/Play, five cards, Track replacing the fifth default, Untrack restoring it, and restored pins after refresh. Desktop player/stats/companion fit in a 1600×900 viewport without page scrolling; narrow layout has no page overflow and the five stats scroll horizontally. That initial illustrative-video adapter has since been replaced by the aligned GRF recording described below; video remains excluded from Git/build assets.

Narrative fixture follow-up: six authored story beats × 12 buckets replace per-event blurbs. All 72 messages reviewed against the source recording. Prefix, correction, duplicate, unrelated-recording and pass-through checks pass; browser confirms authored commentary arrives in Insights as replay advances. These remain mock upstream outputs, not deployed narrative generation.

Pinning/recovery follow-up: standard ETL answers now offer Track alongside custom stats. Real-Postgres checks cover live ETL updates, persistence, default-card deduplication, Untrack and clarification-to-custom tracking. In the browser a standard answer stayed at its 20-minute value while the pinned card advanced from 4 to 6. An isolated Docker test changed the backend IP: the original proxy returned 502; the updated proxy recovered to 200 and preserved the path/query string. Header ambiguity instructions now run in the intent router before the statistic planner. Fresh independent review found no further issues.

Real-model follow-up: the viewer asked for clarification of Bruno Fernandes headers. A separate disposable-schema run then verified the complete dialogue: headed shots including goals → 3 → successful Track, retaining the player from the original question. The planner needed one schema repair and succeeded within its configured repair budget. This used the real development model and fixture upstreams, not fixture agent replies.

Audience follow-up: separate team and viewer-style controls cover all 12 combinations without changing identity, chat or tracked stats. The real-Postgres suite covers presence flags, shared combinations, takeover, disconnect, restart, reset and failure races. Browser selection changed the persisted generation target to `home:experienced`, then `neutral:simple`; refresh retained the latter and its tracked stat. All definitions remain stored. Narrow-layout inspection showed no horizontal page overflow. The final selected-audience question-context assertion passed separately after the full suite. Fresh independent review was clean. Presence is currently owned by one backend process; the planned narrative generator consumes enabled targets, while the mock service still serves prewritten fixtures.

Aligned GRF follow-up: the rendered Chelsea–United match is exactly 720 seconds, 1280×720 at 25 fps. Its 1,321 event deliveries share the video timeline; all four goal score changes were checked against footage. Full video decoding passed. The separate ETL owns raw history and standard projections in two local PostgreSQL databases; the narrative stub owns 144 manually authored versions (12 video minutes × 12 buckets) and neutral recap tiers in SQLite. Only enabled audience versions are delivered. The source hash and event evidence bind the commentary to this exact match.

Browser verification: the actual Docker viewer played matching footage, streamed ETL-owned percentages and counters, displayed the first authored narrative, and answered a completed-pass question with 13 at its observed snapshot. Tracking that offer produced a live card which reached 15 without changing the historical answer. Unsupported body-part/card/corner measurements are unavailable rather than fabricated zeros. Fresh recording/integration and narrative reviews found no remaining issues in their scopes.

This uses the documented metadata HTTP checkpoint bridge, not production Event Hubs/Service Bus or Stream Analytics. SQLite/PostgreSQL are explicit local substitutes for planned upstream Azure stores. The neutral narrative engine is still an authored demo stub, not the production LLM workflow. Named-player attempt totals can be incomplete when scorer attribution is unknown; this limitation is included in agent context and the generator guide.
