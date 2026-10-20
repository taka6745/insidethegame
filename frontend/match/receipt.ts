import type { Reply, Usage } from "./types.ts";

/** Estimated cost uses a fixed price the viewer sets, never any provider's real pricing. */
export interface Prices {
  /** US dollars per million input tokens. */
  input: number;
  /** US dollars per million output tokens. */
  output: number;
}
export const DEFAULT_PRICES: Prices = { input: 0.4, output: 1.6 };
const KEY = "itg-answer-prices";

export function loadPrices(storage?: Pick<Storage, "getItem">): Prices {
  try {
    const saved = JSON.parse((storage ?? globalThis.localStorage)?.getItem(KEY) || "null");
    if (saved && [saved.input, saved.output].every((n) => Number.isFinite(n) && n >= 0))
      return { input: saved.input, output: saved.output };
  } catch {
    // Private windows and blocked storage fall back to the defaults.
  }
  return { ...DEFAULT_PRICES };
}
export function savePrices(prices: Prices, storage?: Pick<Storage, "setItem">) {
  try {
    (storage ?? globalThis.localStorage)?.setItem(KEY, JSON.stringify(prices));
  } catch {
    // The settings still apply for this page.
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

/** "✓ 3 facts · 1.8k tok · 4.2s · $0.001", with the token split and calls for a tooltip. */
export function receipt(facts: number, usage: Usage, prices: Prices): { line: string; detail: string } {
  const tokens = usage.input_tokens + usage.output_tokens;
  const cost = (usage.input_tokens * prices.input + usage.output_tokens * prices.output) / 1_000_000;
  const line = [
    facts ? `✓ ${facts} ${facts === 1 ? "fact" : "facts"}` : "",
    usage.calls ? `${compactCount(tokens)} tok` : "",
    `${usage.seconds.toFixed(1)}s`,
    usage.calls ? dollars(cost) : "",
  ].filter(Boolean).join(" · ");
  const detail = usage.calls
    ? `${usage.input_tokens.toLocaleString("en")} input + ${usage.output_tokens.toLocaleString("en")} output tokens · `
      + `${usage.calls} model ${usage.calls === 1 ? "call" : "calls"} · cost estimated at your price settings`
    : "Answered without a model call";
  return { line, detail };
}
