# Viewer narrative fixtures

[`viewer-narratives.json`](viewer-narratives.json) contains six authored story beats for the two bundled fictional recordings. Each beat has 12 short versions: home, away or neutral × simple, casual, experienced or analytical.

```text
Received demo events → evidence gates → prewritten bucket message
                                      ↓
                         fake narrative GraphQL → backend → Insights
```

These are synthetic editorial examples, not model output or a production pattern detector. The mock emits a beat only after its trigger and supporting events arrive. It uses the corrected event view, keeps IDs stable and does not turn each event into another insight. There are no model calls or per-viewer generation loops.

The recording fingerprint, received event prefix and roster must match a bundled recording. Edited/uploaded recordings receive no scripted commentary; they need their own fixtures or the real narrative service. A file/roster change therefore requires updating and retesting this fixture deliberately.

Text uses named roster placeholders; the mock upstream resolves them before delivery. The backend only routes the already-framed messages, and the frontend renders the text unchanged. Standard-stat recommendations still come from the upstream fixture. Neutral recap history for questions remains a separate test double.

**Evidence limits:** the sparse feed supports chances, repeated corners, a red card and a late goal. It does not establish possession, formation, xG, player intent or a causal connection between the corners and the eventual goal. The 95-minute beat is a late-game update, not a claimed final whistle. Simulator footage remains a separate illustrative source.

To change the demo copy, edit the JSON and restart `fake-narrative`. Keep evidence IDs with each beat and run `tests/test_viewer_narratives.py` plus `tests/test_product.py` through the backend test container.
