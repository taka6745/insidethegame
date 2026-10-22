import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";

const root = new URL("../", import.meta.url);
const league = JSON.parse(readFileSync(new URL("../data-generation/grf_demo/league.json", root), "utf8")) as {
  league: { name: string; wordmark: string; wordmark_light: string; disclaimer: string };
  clubs: Record<string, { name: string; crest: string }>;
};
const html = readFileSync(new URL("match/index.html", root), "utf8");
const asset = (path: string) => new URL(path.slice(1), root);

test("the viewer shows the fictional league from the shared mapping, with no real league branding", () => {
  assert.ok(html.includes(league.league.wordmark_light));
  assert.ok(html.includes(`alt="${league.league.name}"`));
  assert.ok(html.includes(league.league.disclaimer));
  assert.doesNotMatch(html, /premier ?league/i);
  assert.doesNotMatch(readFileSync(new URL("match/styles.css", root), "utf8"), /premier ?league/i);
  for (const path of [league.league.wordmark, league.league.wordmark_light]) assert.ok(existsSync(asset(path)), path);
});

test("every club in the mapping has its own crest file", () => {
  for (const club of Object.values(league.clubs)) assert.ok(existsSync(asset(club.crest)), club.crest);
});

test("no third-party sting or league font ships", () => {
  assert.ok(!existsSync(new URL("assets/league/sting", root)) || readdirSync(new URL("assets/league/sting", root)).length === 0);
  assert.ok(!existsSync(new URL("assets/league/fonts", root)));
});
