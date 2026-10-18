/** Opt-in client algorithm/transfer budget; not a DOM, network or viewer-capacity test. */
import { readFile, readdir } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import { performance } from "node:perf_hooks";
import { currentSnapshot } from "../match/format.js";

const root = new URL("../", import.meta.url);
const files = (await readdir(new URL("match/", root))).filter((name) =>
  /\.(js|css|html)$/.test(name),
);
const icons = ["pitch", "insight", "track"].map(
  (name) => `assets/icons/${name}.svg`,
);
const brandAssets = [
  "assets/league/premier-league-white.svg",
  "assets/league/premier-league.svg",
  "assets/league/microsoft.svg",
  "assets/league/clubs/chelsea.svg",
  "assets/league/clubs/manutd.svg",
  "assets/league/fonts/PremierLeague-Regular.woff2",
  "assets/league/fonts/PremierLeague-Bold.woff2",
];
const sizes = await Promise.all(
  [...files.map((name) => `match/${name}`), ...icons, ...brandAssets].map(
    async (file) => {
      const bytes = await readFile(new URL(file, root));
      return { file, bytes: bytes.length, gzip: gzipSync(bytes).length };
    },
  ),
);
const total = (rows) =>
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
  match: { run_id: "benchmark" },
  events,
  narratives: Array(40).fill({ text: "Synthetic bounded narrative." }),
  cards: Array(3).fill({ value: 1 }),
};
let state;
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
  state.events.length === 60 &&
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
