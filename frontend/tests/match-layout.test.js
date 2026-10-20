import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../match/index.html", import.meta.url), "utf8");

test("viewer keeps the stream, stats and companion while raw events stay in the lab", () => {
  assert.match(html, /<video\b[^>]*id="match-video"[^>]*playsinline[^>]*>/);
  const video = html.match(/<video\b[^>]*>/)[0];
  assert.doesNotMatch(video, /\bcontrols\b/); // Native seeking is outside this demo's scope.
  assert.ok(html.indexOf('id="match-video"') < html.indexOf('id="stats"'));
  assert.match(html, /id="stories-panel"/);
  assert.match(html, /id="questions-panel"/);
  assert.doesNotMatch(html, /id="(?:events|event-title|timeline-title)"/);
  assert.match(html, /Demo footage unavailable/);
  assert.match(html, /href="\/lab\/"/);
});
