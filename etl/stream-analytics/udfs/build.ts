// Compiles src/*.ts to the plain `function main` scripts Terraform uploads as Stream Analytics UDFs.
// node build.ts          write udfs/*.js
// node build.ts --check  fail if any udfs/*.js differs from its compiled src/*.ts
// tsc: $TSC, else the frontend's (npm ci in frontend/), else tsc on PATH.
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const here = import.meta.dirname;
const check = process.argv.includes("--check");
const frontendTsc = join(here, "../../../frontend/node_modules/.bin/tsc");
const tsc = process.env.TSC || (existsSync(frontendTsc) ? frontendTsc : "tsc");

const out = mkdtempSync(join(tmpdir(), "udfs-"));
const stale: string[] = [];
try {
  execFileSync(tsc, ["-p", here, "--outDir", out], { stdio: "inherit" });
  for (const file of readdirSync(join(here, "src")).filter(f => f.endsWith(".ts") && f !== "types.ts").sort()) {
    const name = file.slice(0, -3);
    const body = readFileSync(join(out, `${name}.js`), "utf8");
    if (!/^function main\(/m.test(body) || /^\s*(import|export)\b/m.test(body)) {
      throw new Error(`${file} must compile to a plain function main script`);
    }
    const script = `// GENERATED from src/${file} by build.ts. Do not edit; edit the .ts and run \`node build.ts\`.\n${body}`;
    const target = join(here, `${name}.js`);
    if (check) {
      if (!existsSync(target) || readFileSync(target, "utf8") !== script) stale.push(`${name}.js`);
    } else {
      writeFileSync(target, script);
    }
  }
  const sources = new Set(readdirSync(join(here, "src")).map(f => f.replace(/\.ts$/, ".js")));
  stale.push(...readdirSync(here).filter(f => f.endsWith(".js") && !sources.has(f)).map(f => `${f} (no source)`));
} finally {
  rmSync(out, { recursive: true, force: true });
}
if (stale.length) {
  console.error(`UDF scripts out of date with src/ (rebuild: node etl/stream-analytics/udfs/build.ts): ${stale.join(", ")}`);
  process.exit(1);
}
