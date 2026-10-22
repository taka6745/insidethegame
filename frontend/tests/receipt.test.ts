import test from "node:test";
import assert from "node:assert/strict";
import { answerFacts, compactCount, cachedPrices, cachePrices, receipt, validPrices } from "../match/receipt.ts";

const usage = { input_tokens: 1450, output_tokens: 350, calls: 2, seconds: 4.236 };

test("receipt line is compact: facts, tokens, seconds and estimated cost", () => {
  const { line, detail } = receipt(3, usage, { input: 0.4, output: 1.6 });
  assert.equal(line, "✓ 3 facts · 1.8k tok · 4.2s · $0.001");
  assert.match(detail, /1,450 input \+ 350 output tokens · 2 model calls · cost estimated at the configured prices/);
  assert.equal(receipt(1, usage, { input: 400, output: 1600 }).line, "✓ 1 fact · 1.8k tok · 4.2s · $1.140");
  // No model call: no tokens or cost, and no provider anything.
  assert.equal(receipt(0, { input_tokens: 0, output_tokens: 0, calls: 0, seconds: 0.31 }, null).line, "0.3s");
  // Before the server prices arrive: tokens but no cost.
  assert.equal(receipt(3, usage, null).line, "✓ 3 facts · 1.8k tok · 4.2s");
  assert.deepEqual([compactCount(950), compactCount(1834), compactCount(12500)], ["950", "1.8k", "13k"]);
});

test("facts come from evidence, then replay clips, then offered stats", () => {
  assert.deepEqual(answerFacts({ text: "", evidence: [{ id: "stat:x", kind: "stat", label: "Riverton Rovers shots" }] }), ["Riverton Rovers shots"]);
  assert.deepEqual(answerFacts({ text: "", replay: { page: 0, page_size: 12, total_items: 1, seconds: 9, clips: [],
    items: [{ source_id: "e", caption: "28′ Goal" }] } }), ["28′ Goal"]);
  assert.deepEqual(answerFacts({ text: "", offers: [{ id: "o", label: "United corners" }] }), ["United corners"]);
});

test("server prices are cached offline only; invalid or blocked storage shows no cost", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); } };
  assert.equal(cachedPrices(storage), null);
  cachePrices({ input: 2, output: 8, revision: 3 } as never, storage);
  assert.deepEqual(cachedPrices(storage), { input: 2, output: 8 });
  store.set("itg-answer-prices", '{"input":-1,"output":"x"}');
  assert.equal(cachedPrices(storage), null);
  assert.equal(cachedPrices({ getItem: () => { throw new Error("blocked"); } }), null);
  assert.equal(validPrices({ input: 0.4, output: 1.6, revision: 1 }), true);
  assert.equal(validPrices({ input: "0.4", output: 1.6 }), false);
  assert.equal(validPrices(null), false);
});
