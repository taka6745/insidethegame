# benchmarks/

> **In short:** `client.ts` measures the shipped static transfer (gzip bytes of `dist/match/`, `dist/shared/`, icons and league artwork) and the time for bounded state replacements. It does not measure DOM rendering, network fan-out or viewer capacity.

| | |
| --- | --- |
| **Run** | `npm run build` in `frontend`, then `node frontend/benchmarks/client.ts` from the repository root |
| **Output** | JSON: per-file sizes, totals, state-update timing |
| **Status** | Opt-in; not part of `npm test` or CI |
| **Budget** | UI 230 KiB raw / 70 KiB gzip (unminified per-module output, no bundler; about 203 / 63 KiB measured), all assets 250 KiB gzip |
