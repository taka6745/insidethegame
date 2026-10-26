import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../match/index.html", import.meta.url), "utf8");

test("viewer keeps the stream, stats and companion while raw events stay in the lab", () => {
  assert.match(html, /<video\b[^>]*id="match-video"[^>]*playsinline[^>]*>/);
  const video = html.match(/<video\b[^>]*>/)![0];
  assert.doesNotMatch(video, /\bcontrols\b/); // Native seeking is outside this demo's scope.
  assert.ok(html.indexOf('id="match-video"') < html.indexOf('id="stats"'));
  assert.match(html, /id="stories-panel"/);
  assert.match(html, /id="questions-panel"/);
  assert.doesNotMatch(html, /id="(?:events|event-title|timeline-title)"/);
  assert.match(html, /Demo footage unavailable/);
  assert.match(html, /href="\/lab\/"/);
});

test("replay stage has its own player, a Replay badge, Back to live and a live corner picture", () => {
  const replay = html.match(/<video\b[^>]*id="replay-video"[^>]*>/)![0];
  assert.match(replay, /playsinline/);
  assert.match(replay, /muted/);
  assert.doesNotMatch(replay, /\bcontrols\b/);
  assert.match(html, /class="replay-badge"[^>]*>Replay</);
  assert.match(html, /id="replay-caption" class="sr-only" aria-live="polite"/);
  for (const id of ["replay-prev", "replay-pause", "replay-next", "replay-dots"])
    assert.doesNotMatch(html, new RegExp(`id="${id}"`));  // Nothing else covers the picture.
  assert.match(html, /id="pip-return"[^>]*aria-label="Back to live"/);
  assert.match(html, /id="replay-close"[^>]*>Back to live</);
});

test("league nav placeholders are marked as outside the demo; Skip ahead has a page-wide clock picture", () => {
  for (const label of ["Table", "Statistics", "Clubs"])
    assert.match(html, new RegExp(`<span aria-disabled="true" title="Not part of this demo">${label}</span`));
  assert.match(html, /id="match-skip-overlay"[^>]*role="dialog"[^>]*aria-modal="true"[^>]*hidden/);
  assert.match(html, /id="match-skip-clock"/);
});
