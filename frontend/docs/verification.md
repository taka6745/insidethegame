# Viewer verification

Verified locally on 18 October 2026. This is a synthetic demonstration, not a real fixture or a production capacity certification.

| Check | Result |
|---|---|
| Backend regression suite | 399 passed; one existing Starlette/httpx deprecation warning |
| Frontend unit/contract tests | 66 passed |
| Native SVG harness tests | 6 passed; all three icons exceed 80% foreground overlap |
| Separate-service smoke | GraphQL reads, live cards/narratives, corrections and takeover passed |
| Filter lab smoke | 26 presets, 35 deliveries, persisted results and reset passed; leaves Chelsea–United ready |
| Independent agent review | Fresh review clean after fixes; final setup delta also reviewed clean |

Browser checks covered the actual Docker-served viewer: Chelsea–United marks/fonts, live score and standard cards, profile switching, question answers, Track/Untrack, saved chat/pins on refresh, session takeover and narrow layout. A pre-match headed-shot answer stayed at zero while its tracked live card reached three. Restarting the backend mid-replay reconnected without a page reload, exposed Resume match and continued from the saved position. No browser console errors were observed.

`node frontend/benchmarks/client.mjs` passed: 78,933 gzip bytes for all shipped UI/assets (including fonts/marks); UI code alone 19,163 gzip bytes. Ten thousand bounded state replacements took 2.78 ms in this run. This is a local reducer measurement, **not** DOM rendering, delivery latency or concurrent-viewer capacity. Rerun on the target environment rather than treating the timing as a guarantee.

[Live contract and production boundaries](live-contract.md) · [Icon evidence](../assets/README.md) · [Brand asset provenance](../assets/league/PROVENANCE.md)

Companion styling follow-up: public PL Companion UI/CSS inspected; CSS-only prompt/loading/answer motion added with reduced-motion opt-out. Regression checks cover pending-to-complete identity and avoid reanimating restored answers or pin updates. Independent follow-up review clean.

Stream-first follow-up: five ETL-owned stat slots, raw events confined to the lab, compact scorebar and internally scrolling companion. Browser checks confirmed simulator playback, Pause/Play, five cards, Track replacing the fifth default, Untrack restoring it, and restored pins after refresh. Desktop player/stats/companion fit in a 1600×900 viewport without page scrolling; narrow layout has no page overflow and the five stats scroll horizontally. The optional local video is illustrative, not aligned to the fixture, and is excluded from Git/build assets.

Narrative fixture follow-up: six authored story beats × 12 buckets replace per-event blurbs. All 72 messages reviewed against the source recording. Prefix, correction, duplicate, unrelated-recording and pass-through checks pass; browser confirms authored commentary arrives in Insights as replay advances. These remain mock upstream outputs, not deployed narrative generation.
