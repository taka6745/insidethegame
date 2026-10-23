import test from "node:test";
import assert from "node:assert/strict";
import {
  mkdtemp,
  mkdir,
  writeFile,
  readFile,
  rm,
  readdir,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";

const script = new URL("../tools/build.sh", import.meta.url).pathname;
test("build fingerprints modules and CSS together; changed source gets a fresh immutable URL", async () => {
  const temp = await mkdtemp(join(tmpdir(), "itg-fe-build-"));
  try {
    const source = join(temp, "source"),
      output = join(temp, "output");
    await mkdir(join(source, "match"), { recursive: true });
    await writeFile(
      join(source, "match/index.html"),
      '<link href="/match/styles.css"><script src="/match/main.js"></script>',
    );
    await writeFile(join(source, "match/main.js"), 'import "./api.js";');
    await writeFile(join(source, "match/api.js"), "export const version = 1;");
    await writeFile(join(source, "match/styles.css"), "body {color: black;}");
    await mkdir(join(source, "shared"));
    await writeFile(join(source, "shared/dom.js"), "export const node = 1;");
    execFileSync("sh", [script, output, source]);
    const before = await readFile(join(output, "index.html"), "utf8");
    const fingerprint = before.match(/\/app\/([a-f0-9]{20})\//)![1]!;
    assert.ok(before.includes(`/app/${fingerprint}/match/main.js`));
    assert.ok(before.includes(`/app/${fingerprint}/match/styles.css`));
    assert.equal(
      await readFile(join(output, "app", fingerprint, "match", "main.js"), "utf8"),
      'import "./api.js";',
    );
    assert.equal(await readFile(join(output, "app", fingerprint, "shared", "dom.js"), "utf8"), "export const node = 1;");
    execFileSync("sh", [script, output, source]);
    assert.equal(await readFile(join(output, "index.html"), "utf8"), before);
    await writeFile(join(source, "match/api.js"), "export const version = 2;");
    execFileSync("sh", [script, output, source]);
    assert.notEqual(await readFile(join(output, "index.html"), "utf8"), before);
    assert.equal((await readdir(join(output, "app"))).length, 3);  // two builds plus `current`
    const latest = (await readFile(join(output, "index.html"), "utf8")).match(/\/app\/([a-f0-9]{20})\//)![1]!;
    assert.equal(await readFile(join(output, "app", "current", "match", "api.js"), "utf8"), "export const version = 2;");
    assert.ok(latest !== fingerprint);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});
test("HTML and lab assets revalidate, only fingerprinted application assets are immutable", async () => {
  const nginx = await readFile(
    new URL("../nginx.conf", import.meta.url),
    "utf8",
  );
  assert.match(nginx, /default "no-cache"/);
  assert.match(
    nginx,
    /~\^\/app\/\[0-9a-f\]\+\/ "public, max-age=31536000, immutable"/,
  );
  assert.doesNotMatch(nginx, /max-age=300/);
  // An old fingerprint falls back to the current build instead of a 404 (no hard refresh after a deploy).
  assert.match(nginx, /try_files \$uri \/app\/current\/\$app_file =404;/);
});
test("hls.js ships from this origin with its licence, without a source-map reference", async () => {
  const temp = await mkdtemp(join(tmpdir(), "itg-fe-vendor-"));
  try {
    execFileSync("sh", [new URL("../tools/vendor.sh", import.meta.url).pathname, temp]);
    const module = await readFile(join(temp, "hls.js"), "utf8");
    assert.match(module, /export\s*\{[^}]*as default/);
    assert.doesNotMatch(module, /sourceMappingURL/);
    assert.match(await readFile(join(temp, "hls.LICENSE.txt"), "utf8"), /Apache|License/);
    const pinned = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
    assert.match(pinned.dependencies["hls.js"], /^\d+\.\d+\.\d+$/);
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
});
