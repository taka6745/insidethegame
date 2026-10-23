import test from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findTerms, loadTerms, parseTerms, scan } from "../devtools/check-bundle.ts";

test("deny-list terms come from the environment or an ignored file, never the repository", () => {
  assert.deepEqual(parseTerms("# comment\nAcme-Model-7, acme\n\nacme"), ["acme-model-7", "acme"]);
  assert.deepEqual(loadTerms({ BUNDLE_DENYLIST: "Foo,bar" }), ["foo", "bar"]);
  assert.deepEqual(loadTerms({ BUNDLE_DENYLIST_FILE: "/nonexistent/denylist.txt" }), []);
  assert.deepEqual(findTerms("const m = 'ACME-model-7';", ["acme-model-7", "other"]), ["acme-model-7"]);
});

test("scan reports files and matched terms in a built tree", async () => {
  const dir = await mkdtemp(join(tmpdir(), "itg-bundle-"));
  try {
    await mkdir(join(dir, "match"));
    await writeFile(join(dir, "match/main.js"), "fetch('/viewer-api/matches')");
    await writeFile(join(dir, "match/leak.js"), "const model = 'Acme-Model-7';");
    assert.deepEqual(await scan(dir, ["acme-model-7"]), [{ file: join("match", "leak.js"), terms: ["acme-model-7"] }]);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("the built bundle names no deny-listed provider or model", async (t) => {
  const dist = new URL("../dist", import.meta.url).pathname;
  const terms = loadTerms();
  if (!terms.length || !existsSync(dist)) return t.skip("set BUNDLE_DENYLIST (or .local/bundle-denylist.txt) and run npm run build");
  const hits = await scan(dist, terms);
  // Report counts only so a failure never prints the configured names.
  assert.deepEqual(hits.map((hit) => `${hit.file}: ${hit.terms.length}`), []);
});
