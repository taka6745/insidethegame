import type { Reply, Usage } from "./types.ts";

/** Answer prices from the backend's `prices` config table (`GET /prices`), never a provider's pricing. */
export interface Prices {
  /** US dollars per million input tokens. */
  input: number;
  /** US dollars per million output tokens. */
  output: number;
}
const KEY = "itg-answer-prices";

export function validPrices(value: unknown): value is Prices {
  const prices = value as Prices | null;
  return Boolean(prices) && [prices!.input, prices!.output].every((n) => typeof n === "number" && Number.isFinite(n) && n >= 0);
}

/** The last server prices this browser saw (an offline cache only), else null: no cost is shown. */
export function cachedPrices(storage?: Pick<Storage, "getItem">): Prices | null {
  try {
    const saved: unknown = JSON.parse((storage ?? globalThis.localStorage)?.getItem(KEY) || "null");
    if (validPrices(saved)) return { input: saved.input, output: saved.output };
  } catch {
    // Private windows and blocked storage wait for the server prices.
  }
  return null;
}
export function cachePrices(prices: Prices, storage?: Pick<Storage, "setItem">) {
  try {
    (storage ?? globalThis.localStorage)?.setItem(KEY, JSON.stringify({ input: prices.input, output: prices.output }));
  } catch {
    // The prices still apply for this page.
  }
}

export function compactCount(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k` : String(value);
}
function dollars(value: number): string {
  return value < 0.001 ? "<$0.001" : `$${value.toFixed(3)}`;
}

/** What an answer stood on: cited stats and events, replay clips, or offered stats. */
export function answerFacts(reply: Reply): string[] {
  const evidence = (reply.evidence || []).map((row) => row.label);
  if (evidence.length) return evidence;
  const clips = (reply.replay?.items || []).map((item) => item.caption || "Clip");
  return clips.length ? clips : (reply.offers || []).map((offer) => offer.label || "Match statistic");
}

/** "✓ 3 facts · 1.8k tok · 4.2s · $0.001", with the token split and calls for a tooltip. Without
 * server prices yet, no cost is shown. */
export function receipt(facts: number, usage: Usage, prices: Prices | null): { line: string; detail: string } {
  const tokens = usage.input_tokens + usage.output_tokens;
  const cost = prices && (usage.input_tokens * prices.input + usage.output_tokens * prices.output) / 1_000_000;
  const line = [
    facts ? `✓ ${facts} ${facts === 1 ? "fact" : "facts"}` : "",
    usage.calls ? `${compactCount(tokens)} tok` : "",
    `${usage.seconds.toFixed(1)}s`,
    usage.calls && cost !== null ? dollars(cost) : "",
  ].filter(Boolean).join(" · ");
  const detail = usage.calls
    ? `${usage.input_tokens.toLocaleString("en")} input + ${usage.output_tokens.toLocaleString("en")} output tokens · `
      + `${usage.calls} model ${usage.calls === 1 ? "call" : "calls"} · ${cost === null ? "prices not loaded yet" : "cost estimated at the configured prices"}`
    : "Answered without a model call";
  return { line, detail };
}
