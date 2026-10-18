# Viewer verification

Verified locally on 18 October 2026. This is a synthetic demonstration, not a real fixture or a production capacity certification.

| Check | Result |
|---|---|
| Backend regression suite | 392 passed; one existing Starlette/httpx deprecation warning |
| Frontend unit/contract tests | 60 passed |
| Native SVG harness tests | 6 passed; all three icons exceed 80% foreground overlap |
| Separate-service smoke | GraphQL reads, live cards/narratives, corrections and takeover passed |
| Filter lab smoke | 26 presets, 35 deliveries, persisted results and reset passed; leaves Chelsea–United ready |
| Independent agent review | Fresh review clean after fixes; final setup delta also reviewed clean |

Browser checks covered the actual Docker-served viewer: Chelsea–United marks/fonts, live score and standard cards, profile switching, question answers, Track/Untrack, saved chat/pins on refresh, session takeover and narrow layout. A pre-match headed-shot answer stayed at zero while its tracked live card reached three. Restarting the backend mid-replay reconnected without a page reload, exposed Resume match and continued from the saved position. No browser console errors were observed.

`node frontend/benchmarks/client.mjs` passed: 81,063 gzip bytes for all shipped UI/assets (including fonts/marks); UI code alone 21,293 gzip bytes. Ten thousand bounded state replacements took 3.73 ms in this run. This is a local reducer measurement, **not** DOM rendering, delivery latency or concurrent-viewer capacity. Rerun on the target environment rather than treating the timing as a guarantee.

[Live contract and production boundaries](live-contract.md) · [Icon evidence](../assets/README.md) · [Brand asset provenance](../assets/league/PROVENANCE.md)

Companion styling follow-up: public PL Companion UI/CSS inspected; CSS-only prompt/loading/answer motion added with reduced-motion opt-out. Regression checks cover pending-to-complete identity and avoid reanimating restored answers or pin updates. Independent follow-up review clean.
