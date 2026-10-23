/** Opt-in client algorithm/transfer budget; not a DOM, network or viewer-capacity test. Run `npm run build` first. */
import { readFile, readdir } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { performance } from "node:perf_hooks";
import { currentSnapshot } from "../match/format.ts";
import type { Snapshot } from "../match/types.ts";

interface Size {
  file: string;
  bytes: number;
  gzip: number;
}

const root = new URL("../", import.meta.url);
// Measure the shipped bundle: compiled modules plus copied HTML/CSS.
const files = (
  await Promise.all(
    ["match", "shared"].map(async (dir) =>
      (await readdir(new URL(`dist/${dir}/`, root)))
        .filter((name) => /\.(js|css|html)$/.test(name))
        .map((name) => `dist/${dir}/${name}`),
    ),
  )
).flat();
const icons = ["pitch", "insight", "track"].map(
  (name) => `assets/icons/${name}.svg`,
);
const brandAssets = [
  "assets/league/elephant-league-white.svg",
  "assets/league/elephant-league.svg",
  "assets/league/microsoft.svg",
  "assets/league/clubs/riverton.svg",
  "assets/league/clubs/forgeham.svg",
];
const sizes = await Promise.all(
  [...files, ...icons, ...brandAssets].map(
    async (file): Promise<Size> => {
      const bytes = await readFile(new URL(file, root));
      return { file, bytes: bytes.length, gzip: gzipSync(bytes).length };
    },
  ),
);
const total = (rows: Size[]) =>
  rows.reduce(
    (total, file) => ({
      bytes: total.bytes + file.bytes,
      gzip: total.gzip + file.gzip,
    }),
    { bytes: 0, gzip: 0 },
  );
const totals = total(sizes);
const uiCode = total(sizes.filter((row) => !brandAssets.includes(row.file)));
const events = Array.from({ length: 60 }, (_, index) => ({
  event_id: `event-${index}`,
  match_time_seconds: index * 60,
  event_type: "pass",
}));
const base = {
  type: "snapshot",
  match: { id: "benchmark" },
  events,
  narratives: Array(40).fill({ text: "Synthetic bounded narrative." }),
  cards: Array(5).fill({ value: 1 }),
};
let state: Snapshot | null | undefined;
const started = performance.now();
for (let version = 0; version < 10000; version++)
  state = currentSnapshot(state, { ...base, version });
const elapsed = performance.now() - started;
const budgets = {
  ui_uncompressed: 100 * 1024,
  ui_gzip: 30 * 1024,
  all_assets_gzip: 250 * 1024,
};
const passed =
  uiCode.bytes <= budgets.ui_uncompressed &&
  uiCode.gzip <= budgets.ui_gzip &&
  totals.gzip <= budgets.all_assets_gzip &&
  state?.events.length === 60 &&
  state.narratives.length === 40;
console.log(
  JSON.stringify(
    {
      scope:
        "Static transfer and bounded state reducer only. No DOM/network/enterprise-capacity claim.",
      totals,
      ui_code: uiCode,
      budgets,
      updates: 10000,
      elapsed_ms: Number(elapsed.toFixed(2)),
      updates_per_second: Math.round((10000 / elapsed) * 1000),
      passed,
      files: sizes,
    },
    null,
    2,
  ),
);
if (!passed) process.exitCode = 1;
