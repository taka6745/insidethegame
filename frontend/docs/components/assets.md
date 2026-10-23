# assets/

> **In short:** three small native SVG feature icons with their verification harness, and the fictional league's original artwork. Both ship in the image (`assets/icons/`, `assets/league/`); `reference/` holds development evidence only.

| | |
| --- | --- |
| **Icons** | `icons/insight.svg`, `icons/track.svg` (shown in the viewer); `icons/pitch.svg` (kept for the harness, not used by the UI) |
| **League artwork** | `league/` wordmarks and six club crests (original artwork) and `microsoft.svg` (attribution only); provenance in [`assets/league/PROVENANCE.md`](../../assets/league/PROVENANCE.md) |
| **Not shipped** | `reference/` (generated sheet, comparison, results) |

## 1. Icon harness

*In short: generated reference → native SVG reconstruction → foreground comparison.*

![Generated reference, SVG render, and overlap](../../assets/reference/icon-comparison.png)

The top row is the generated reference, the middle is the shipped SVG, and the bottom overlays both. Black overlaps; red/cyan differ.

| Icon | Overlap | Native shapes |
|---|---:|---:|
| Pitch | 93.56% | 3 |
| Insight | 89.94% | 2 |
| Track | 83.06% | 2 |

The gate is **80% normalized intersection-over-union of foreground pixels**, not an image score inflated by white background. Each image is thresholded, cropped to its foreground and fitted into the same 128px box preserving aspect ratio. No translation search, distortion or per-pixel path tracing. A separate budget allows at most 8 native shapes, 40 explicit path commands, 160 path/point numeric tokens and 2 KiB per icon; embedded raster images are rejected. The numeric budget also catches implicit repeated path segments.

These three SVGs were reconstructed as intentional geometry from the generated sheet. This is a repeatable verification harness, not an automatic vectorizer for arbitrary images. Edit the SVG shapes and rerun the check. A passing overlap score does not replace inspection at small sizes.

```sh
uv venv .local/icon-venv
uv pip install --python .local/icon-venv/bin/python -r frontend/devtools/icon-requirements.txt
.local/icon-venv/bin/python frontend/devtools/check_icons.py
.local/icon-venv/bin/python -m unittest discover -s frontend/devtools -p 'test_*.py'
```

Cairo is required by CairoSVG (`brew install cairo` on macOS or `libcairo2` on Debian). On Apple Silicon, if the dynamic library is not found, prefix the last two commands with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.

## 2. Provenance

*In short: icons generated then rebuilt by hand; league artwork original; only the Microsoft logo is third-party.*

Original project artwork generated with the built-in image tool on 18 October 2026, then rebuilt with native SVG. These three feature icons contain no Elephant League, Microsoft or club marks. The league artwork in `league/` is separate original artwork ([provenance](../../assets/league/PROVENANCE.md)) and is not subject to this reconstruction harness. Reference sheets and test outputs are development evidence and are not shipped to browsers.

**Prompt:** Create a white three-column reference sheet with black monoline icons on a 24-unit grid: a vertical football pitch with halfway line, circle and penalty boxes; a rounded speech bubble with two lines; a bookmark with a plus sign. Use round caps/joins, consistent optical weight, simple geometry and generous spacing. No labels, gradients, shadows, texture or extra decoration.
