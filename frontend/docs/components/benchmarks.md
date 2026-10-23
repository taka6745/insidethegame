# benchmarks/

> **In short:** `client.ts` measures the shipped static transfer (gzip bytes of `dist/match/`, `dist/shared/`, icons and league artwork) and the time for bounded state replacements. It does not measure DOM rendering, network fan-out or viewer capacity.

| | |
| --- | --- |
| **Run** | `npm run build` in `frontend`, then `node frontend/benchmarks/client.ts` from the repository root |
| **Output** | JSON: per-file sizes, totals, state-update timing |
| **Status** | Opt-in; not part of `npm test` or CI. The UI budget (30 KiB gzip) is exceeded: about 63 KiB on 23 Oct, so `passed` is `false` |
