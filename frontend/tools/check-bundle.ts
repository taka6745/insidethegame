// Fails when a built file names any deny-listed term (e.g. a model provider or model id).
// The terms never live in the repository: BUNDLE_DENYLIST (comma or newline separated), or the file
// at BUNDLE_DENYLIST_FILE, default <repo>/.local/bundle-denylist.txt (ignored). Lines starting # are comments.
// Usage: node tools/check-bundle.ts [dist]
import { readdir, readFile } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

export const DEFAULT_DENYLIST = new URL("../../.local/bundle-denylist.txt", import.meta.url).pathname;

export function parseTerms(text: string): string[] {
  return [...new Set(text.split(/[\n,]/).map((term) => term.trim().toLowerCase())
    .filter((term) => term && !term.startsWith("#")))];
}

/** Terms from the environment, else the ignored file; empty when neither is configured. */
export function loadTerms(env: Record<string, string | undefined> = process.env): string[] {
  if (env.BUNDLE_DENYLIST) return parseTerms(env.BUNDLE_DENYLIST);
  const file = env.BUNDLE_DENYLIST_FILE || DEFAULT_DENYLIST;
  return existsSync(file) ? parseTerms(readFileSync(file, "utf8")) : [];
}

/** Case-insensitive; reports which terms matched, never the surrounding text. */
export function findTerms(text: string, terms: readonly string[]): string[] {
  const lower = text.toLowerCase();
  return terms.filter((term) => lower.includes(term));
}

export async function scan(dir: string, terms: readonly string[]) {
  const hits: { file: string; terms: string[] }[] = [];
  const walk = async (path: string): Promise<void> => {
    for (const entry of await readdir(path, { withFileTypes: true })) {
      const full = join(path, entry.name);
      if (entry.isDirectory()) await walk(full);
      else {
        const found = findTerms(await readFile(full, "latin1"), terms);
        if (found.length) hits.push({ file: relative(dir, full), terms: found });
      }
    }
  };
  await walk(dir);
  return hits;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const dir = process.argv[2] || new URL("../dist", import.meta.url).pathname;
  const terms = loadTerms();
  if (!terms.length) {
    console.error("No deny-list configured: set BUNDLE_DENYLIST or create .local/bundle-denylist.txt.");
    process.exit(2);
  }
  const hits = await scan(dir, terms);
  // Print term counts and files only, so the check never echoes the configured names.
  for (const hit of hits) console.error(`${hit.file}: ${hit.terms.length} deny-listed term(s)`);
  if (hits.length) process.exit(1);
  console.log(`Bundle clean: ${terms.length} deny-listed terms checked.`);
}
