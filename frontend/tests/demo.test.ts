import test from "node:test";
import assert from "node:assert/strict";
import { DemoApi, DemoControls, SkipOverlay, demoMatches, labelSeconds, mainToOpen, showLiveFrom, showSkip, withRunClocks }
  from "../match/demo.ts";
import { AudienceView } from "../match/audience-view.ts";
import { stub } from "./support.ts";

class El {
  [key: string]: unknown;
  children: El[] = [];
  hidden = false;
  disabled = false;
  dataset: Record<string, string> = {};
  id = "";
  append(...children: El[]) { this.children.push(...children); }
  value = "";
  textContent = "";
  className = "";
  title = "";
  style: Record<string, string> = {};
  replaceChildren(...children: El[]) { this.children = children; }
  listeners: Record<string, () => void> = {};
  addEventListener(name: string, fn: () => void) { this.listeners[name] = fn; }
}
function doc() {
  const nodes = new Map<string, El>();
  return {
    nodes,
    document: stub<Document>({
      createElement: () => new El(),
      getElementById: (id: string) => nodes.get(id) ?? nodes.set(id, new El()).get(id),
    }),
  };
}

test("the demo API posts the chosen start point and surfaces the operator's refusal", async () => {
  const calls: [string, RequestInit][] = [];
  const api = new DemoApi(async (url, init) => {
    calls.push([url, init]);
    return url.endsWith("start")
      ? { ok: false, status: 409, json: async () => ({ detail: "No seed is recorded for 20′ yet." }) }
      : { ok: true, status: 200, json: async () => ({ points: [], live: false }) };
  });
  await assert.rejects(api.start("20"), /No seed is recorded/);
  assert.deepEqual([calls[0]![0], JSON.parse(String(calls[0]![1].body))], ["/demo-api/start", { point: "20" }]);
  assert.equal((await api.state()).live, false);
});

test("an accepted start waits on the operator's state, then returns how it ended or its refusal", async () => {
  const states = [{ points: [], live: false, pending: ["start"] },
    { points: [], live: true, pending: [], last: { action: "start", ok: true, started: true, live_from: "20′" } }];
  const api = new DemoApi(async (url) => url.endsWith("start")
    ? { ok: true, status: 202, json: async () => ({ accepted: true, pending: ["start"] }) }
    : { ok: true, status: 200, json: async () => states.shift() ?? {} });
  const result = await api.settled("start", api.call("start", { point: "20" }), 0);
  assert.deepEqual([result.started, result.live_from], [true, "20′"]);
  const failing = new DemoApi(async (url) => url.endsWith("cancel")
    ? { ok: true, status: 202, json: async () => ({ accepted: true }) }
    : { ok: true, status: 200, json: async () => ({ points: [], live: true, pending: [],
      last: { action: "cancel", ok: false, detail: "Could not cancel the demo; try again." } }) });
  await assert.rejects(failing.settled("cancel", failing.call("cancel", {}), 0), /Could not cancel/);
});

test("start points without a seed are offered but disabled; a live demo shows only Cancel", () => {
  const { nodes, document } = doc();
  const controls = new DemoControls(document, stub<DemoApi>({}));
  controls.render({ live: false, points: [{ id: "kickoff", label: "Kick-off", ready: true }, { id: "20", label: "20′", ready: false }] });
  const options = nodes.get("demo-point")!.children;
  assert.deepEqual(options.map((o) => [o.value, o.disabled]), [["kickoff", false], ["20", true]]);
  assert.deepEqual([nodes.get("demo-start")!.hidden, nodes.get("demo-cancel")!.hidden], [false, true]);
  controls.render({ live: true, points: [] });
  assert.equal(document.getElementById("demo-live-from")!.hidden, true);  // a kick-off demo needs no note
  controls.render({ live: true, points: [], live_from: "60′" });
  assert.equal(document.getElementById("demo-live-from")!.textContent,
    "The story so far was generated earlier on this pipeline; live from 60′.");
  assert.deepEqual([nodes.get("demo-start")!.hidden, nodes.get("demo-cancel")!.hidden], [true, false]);
});

test("Cancel demo asks in the page and cancels only once confirmed", async () => {
  const { nodes, document } = doc();
  let cancels = 0, opened = 0;
  const controls = new DemoControls(document, stub<DemoApi>({
    cancel: async () => { cancels += 1; return {}; },
    state: async () => ({ live: false, points: [] }),
  }));
  const dialog = nodes.get("demo-cancel-dialog")!;
  dialog.showModal = () => { opened += 1; };
  const original = globalThis.confirm;
  globalThis.confirm = () => assert.fail("no native confirm");
  try {
    for (const answer of ["keep", ""]) {  // Keep watching, then Escape
      nodes.get("demo-cancel")!.listeners.click!();
      assert.equal(dialog.returnValue, "");
      dialog.returnValue = answer;
      dialog.listeners.close!();
    }
    await new Promise((done) => setTimeout(done));
    assert.deepEqual([opened, cancels], [2, 0]);
    nodes.get("demo-cancel")!.listeners.click!();
    dialog.returnValue = "confirm";
    dialog.listeners.close!();
    await new Promise((done) => setTimeout(done));
    assert.equal(cancels, 1);
    assert.equal(controls.busy, false);
  } finally {
    globalThis.confirm = original;
  }
});

test("while a demo is on the picker lists only its matches", () => {
  const matches = [{ match_id: "a", status: "live" }, { match_id: "b", status: "finished" }, { match_id: "c", status: "scheduled" }];
  assert.deepEqual(demoMatches(matches, true).map((m) => m.match_id), ["a", "c"]);
  assert.equal(demoMatches(matches, false).length, 3);
});

test("seed-recording runs are never listed, and a live demo lists only its own runs", () => {
  // A recording run stops at its hold point (20′): a viewer opening it would see the match freeze there.
  const matches = [{ match_id: "demo", status: "live" }, { match_id: "rec", status: "live" }, { match_id: "old", status: "live" }];
  assert.deepEqual(demoMatches(matches, false, null, new Set(), new Set(["rec"])).map((m) => m.match_id), ["demo", "old"]);
  assert.deepEqual(demoMatches(matches, true, "demo", new Set(["demo"]), new Set(["rec"])).map((m) => m.match_id), ["demo"]);
  const { document } = doc();
  const controls = new DemoControls(document, stub<DemoApi>({}));
  controls.render({ live: true, points: [], runs: [{ match_id: "demo" }], recording: [{ match_id: "rec" }] });
  assert.deepEqual([[...controls.runs], [...controls.recording]], [["demo"], ["rec"]]);
});

test("a live demo lists its main game first and opens it unless the viewer came to choose another", () => {
  const matches = [{ match_id: "c" }, { match_id: "main" }, { match_id: "b", status: "finished" }];
  assert.deepEqual(demoMatches(matches, true, "main").map((m) => m.match_id), ["main", "c"]);
  const on = { live: true, main: "main", started: false, watching: false };
  assert.equal(mainToOpen(on, matches, false), "main");
  assert.equal(mainToOpen(on, matches, true), null);  // ← All matches: switch games
  assert.equal(mainToOpen({ ...on, started: true }, matches, true), "main");  // just pressed Start demo
  assert.equal(mainToOpen(on, [{ match_id: "c" }], false), null);  // not listed yet (before its MA1)
  assert.equal(mainToOpen({ ...on, live: false }, matches, false), null);
  assert.equal(mainToOpen({ ...on, started: true, watching: true }, matches, false), null);  // start-up still showing
  const { document } = doc();
  const controls = new DemoControls(document, stub<DemoApi>({}));
  controls.render({ live: true, points: [], main_match_id: "main" });
  assert.equal(controls.main, "main");
  controls.render({ live: false, points: [], main_match_id: "main" });
  assert.equal(controls.main, null);
});

test("viewers can change their team and style while the match is live", () => {
  const { document } = doc();
  const view = new AudienceView(document);
  view.connection(true);
  const buckets = [{ id: "x", label: "X" }, { id: "y", label: "Y" }];
  view.render(stub({ audience_buckets: buckets, match: { status: "scheduled" } }));
  assert.equal(view.select.disabled, false);
  view.render(stub({ audience_buckets: buckets, match: { status: "live" } }));
  assert.equal(view.select.disabled, false);
  view.setBusy(true);
  assert.equal(view.select.disabled, true);  // only while a change is in flight
});

import { DemoProgress, follow } from "../match/demo-progress.ts";

test("pipeline progress lights each stage from the status and captions the first that is waking", () => {
  const { nodes, document } = doc();
  const progress = new DemoProgress(document);
  const stages = ["feed", "event-hubs", "etl", "service-bus", "engine", "backend", "viewer"];
  const done = progress.render({ live: true, matches: 3, stages: stages.map((id, i) => ({ id, ready: i < 2 })) });
  assert.equal(done, false);
  assert.deepEqual([...progress.nodes.values()].map((n) => (n as unknown as El).dataset), stages.map((_, i) => ({ stage: stages[i], ready: i < 2 ? "yes" : "no" })));
  assert.equal(nodes.get("demo-progress-caption")?.textContent, "Waking the ETL");
});

test("while a start runs, warm stages alone do not finish the picture: the viewer stage waits for a live demo", () => {
  const { nodes, document } = doc();
  const progress = new DemoProgress(document);
  progress.awaitLive = true;
  const warm = { live: false, matches: 0, stages: ["feed", "viewer"].map((id) => ({ id, ready: true })) };
  assert.equal(progress.render(warm), false);
  assert.equal(nodes.get("demo-progress-caption")?.textContent, "Starting the matches");
  assert.equal(progress.render({ ...warm, live: true, matches: 3 }), true);
  progress.awaitLive = false;
  assert.equal(progress.render(warm), true);
});

test("follow polls until every stage is ready, then hides", async () => {
  const seen: boolean[] = [];
  let calls = 0;
  const ok = await follow(async () => ({ live: true, matches: 3, stages: [{ id: "feed", ready: ++calls > 2 }] }),
    { render: (status) => { seen.push(status.stages[0]!.ready); return status.stages[0]!.ready; }, hide: () => seen.push(false) },
    { sleep: async () => {} });
  assert.equal(ok, true);
  assert.deepEqual(seen, [false, false, false, true, false]);  // the pending picture first
});

test("the start-up picture shows every stage waking before the operator has answered", async () => {
  const seen: string[] = [];
  let asked = 0;
  await follow(async () => { asked += 1; throw new Error("operator still waking"); },
    { render: (status) => { seen.push(status.stages.map((s) => `${s.id}:${s.ready}`).join(",")); return false; }, hide: () => seen.push("hidden") },
    { sleep: async () => {}, limit: 1 });
  assert.equal(seen[0], "feed:false,event-hubs:false,etl:false,service-bus:false,engine:false,backend:false,viewer:false");
  assert.ok(asked >= 1);
  assert.equal(seen.at(-1), "hidden");
});

test("Start demo says when a kick-off demo starts, and that a seeded one resumes from its point", async () => {
  const notices: string[] = [];
  for (const result of [{ started: true, runs: [{ match_id: "m", kickoff: "2026-10-22T09:00:00Z" }] },
    { started: true, live_from: "60′", runs: [{ match_id: "m", kickoff: "2026-10-22T08:00:00Z" }] }]) {
    const { document } = doc();
    const controls = new DemoControls(document, stub<DemoApi>({
      start: async () => result, state: async () => { throw new Error("no operator"); },
    }));
    controls.notice = (message) => notices.push(message);
    await controls.start();
  }
  assert.match(notices[0]!, /^Demo starts at /);
  assert.equal(notices[1], "Demo resumes from 60′ in a few seconds.");  // not a kickoff an hour ago
});

test("a match of a seeded demo says the story so far was generated earlier; other matches say nothing", async () => {
  const { document } = doc();
  const from = document.getElementById("match-live-from")!;
  const state = { live: true, points: [], live_from: "20′", runs: [{ match_id: "m1" }] };
  await showLiveFrom(document, "m1", stub<DemoApi>({ state: async () => state }));
  assert.match(from.textContent ?? "", /Live from 20′ · the story so far was generated earlier/);
  assert.equal(from.hidden, false);
  await showLiveFrom(document, "other", stub<DemoApi>({ state: async () => state }));
  assert.equal(from.hidden, true);
  await showLiveFrom(document, "m1", stub<DemoApi>({ state: async () => { throw new Error("no operator"); } }));
  assert.equal(from.hidden, true);
});

test("a match being recorded as a start point says it pauses there instead of looking frozen", async () => {
  const { document } = doc();
  const from = document.getElementById("match-live-from")!;
  const state = { live: false, points: [], recording: [{ match_id: "rec" }] };
  await showLiveFrom(document, "rec", stub<DemoApi>({ state: async () => state }));
  assert.match(from.textContent ?? "", /being recorded as a demo start point and pauses there/);
  assert.equal(from.hidden, false);
});

test("a demo control the browser cannot reach shows a plain sentence, never the network error", async () => {
  const api = new DemoApi(async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(api.state(), (error: Error) => !/fetch/i.test(error.message) && /demo controls/.test(error.message));
  // A script error inside Start shows a plain sentence; the operator's own refusal shows as it is.
  const notices: string[] = [];
  for (const start of [async () => { throw new TypeError("Cannot read properties of undefined (reading 'x')"); },
    () => new DemoApi(async () => ({ ok: false, status: 409, json: async () => ({ detail: "Pick another start point." }) })).start("20")]) {
    const { document } = doc();
    const controls = new DemoControls(document, stub<DemoApi>({ start, state: async () => { throw new Error("no operator"); } }));
    controls.notice = (message) => notices.push(message);
    await controls.start();
  }
  assert.deepEqual(notices, ["The demo could not be changed. Try again shortly.", "Pick another start point."]);
});

test("Skip ahead shows in a playing demo's match, posts the target and says where every match now is", async () => {
  const { nodes, document } = doc();
  const targets = nodes.set("match-skip-targets", new El()).get("match-skip-targets")!;
  targets.querySelectorAll = () => targets.children;
  const posted: unknown[] = [];
  const state = { points: [], live: true, runs: [{ match_id: "m1" }], skips: [{ id: "20", label: "+20′" }] };
  const api = new DemoApi(async (url, init) => {
    if (url.endsWith("skip")) {
      posted.push(JSON.parse(String(init.body)));
      return { ok: true, status: 200, json: async () => ({ skipped_seconds: 1200, target: { label: "+20′" } }) };
    }
    return { ok: true, status: 200, json: async () => state };
  });
  const caches: string[] = [];
  await showSkip(document, "m1", api, { clock: () => 2700,
    caches: { flush: () => caches.push("flush"), resync: async () => { caches.push("resync"); } } });
  assert.equal(nodes.get("match-skip")!.hidden, false);
  assert.deepEqual(targets.children.map((button) => button.textContent), ["+20′"]);  // one button per target
  targets.children[0]!.listeners.click!();
  await new Promise((done) => setTimeout(done, 0));
  assert.deepEqual(posted, [{ target: "20" }]);
  assert.equal(nodes.get("match-skip-note")!.textContent, "Skipped to 65′ in every demo match.");
  assert.deepEqual(caches, ["flush", "resync"]);  // stale states dropped once skipped; a fresh picture after
  await showSkip(document, "other", api);  // not one of the demo's matches: no control
  assert.equal(nodes.get("match-skip")!.hidden, true);
});

/** Timers run by hand: `fire()` runs the timeout, `tick()` one interval. */
function timers() {
  let due: (() => void) | null = null, interval: (() => void) | null = null;
  return {
    setTimeout: (fn: () => void) => { due = fn; return 1; }, clearTimeout: () => { due = null; },
    setInterval: (fn: () => void) => { interval = fn; return 2; }, clearInterval: () => { interval = null; },
    fire: () => due?.(), tick: () => interval?.(), get armed() { return due !== null; }, get ticking() { return interval !== null; },
  };
}

test("the skip overlay runs the clock from the click to the target, blocking everything, and dismisses only once the story caught up", async () => {
  const { nodes, document } = doc();
  const clock = timers();
  const overlay = new SkipOverlay(document, clock);
  const frozen: boolean[] = [];
  overlay.onFreeze = (on) => frozen.push(on);
  const at = (seconds: number, story: number[] = []) => ({ match: { clock_seconds: seconds }, narratives: story.map((clock_seconds) => ({ clock_seconds })) });
  const fill = () => nodes.get("match-skip-fill")!.style.width;
  const shown = overlay.show(2700, 1200, "+20′");  // 45:00 → 65:00, the label's own guess
  assert.deepEqual([nodes.get("match-skip-overlay")!.hidden, frozen, overlay.up], [false, [true], true]);
  assert.equal(nodes.get("match-skip-title")!.textContent, "Skipping ahead to 65′");
  assert.deepEqual([nodes.get("match-skip-clock")!.textContent, nodes.get("match-skip-range")!.textContent, fill()], ["45:00", "45:00 → 65:00", "0%"]);
  overlay.retarget(1800);  // the operator rounded up to 75′
  assert.equal(nodes.get("match-skip-title")!.textContent, "Skipping ahead to 75′");
  overlay.update(at(3000, [2650]));  // insights from before the click are not the skipped story
  clock.tick();
  assert.deepEqual([nodes.get("match-skip-clock")!.textContent, fill()], ["45:15", "1%"]);  // runs towards the latest clock, never a jump
  overlay.update(at(2900));  // an older state never runs the clock back
  overlay.update(at(4500));
  for (let i = 0; i < 500 && overlay.shown < 4500; i += 1) clock.tick();
  assert.deepEqual([nodes.get("match-skip-clock")!.textContent, fill(), overlay.up], ["75:00", "100%", true]);  // the clock alone: insights still trickling in
  overlay.update(at(4500, [2650, 3100]));  // the first insight of the skipped span
  clock.tick();
  assert.equal(await shown, "reached");
  assert.deepEqual([nodes.get("match-skip-overlay")!.hidden, frozen, clock.armed, clock.ticking], [true, [true, false], false, false]);
  // Near enough: the story arrived and the clock is within 30 s of the target.
  const again = overlay.show(0, 600, "+10′");
  overlay.update(at(575, [30]));
  for (let i = 0; i < 500 && overlay.up; i += 1) clock.tick();
  assert.equal(await again, "reached");
});

test("the skip overlay never traps a viewer: it times out with a note, and a failed request takes it down", async () => {
  const { nodes, document } = doc();
  const clock = timers();
  const overlay = new SkipOverlay(document, clock);
  const shown = overlay.show(0, null, "to half-time");  // a label that says no minutes: no target until the response
  assert.deepEqual([nodes.get("match-skip-title")!.textContent, nodes.get("match-skip-range")!.textContent, clock.armed],
    ["Skipping ahead to half-time…", "from 0:00", true]);
  clock.fire();
  assert.equal(await shown, "timeout");
  assert.equal(nodes.get("match-skip-overlay")!.hidden, true);
  const frozen: boolean[] = [];
  overlay.onFreeze = (on) => frozen.push(on);
  void overlay.show(600, 600, "+10′");
  overlay.fail();
  assert.deepEqual([overlay.up, nodes.get("match-skip-overlay")!.hidden, frozen], [false, true, [true, false]]);
  // Through Skip ahead: the response retargets the picture; a timeout leaves the catching-up note, an error the reason.
  const targets = nodes.set("match-skip-targets", new El()).get("match-skip-targets")!;
  targets.querySelectorAll = () => targets.children;
  let fail = false;
  const api = new DemoApi(async (url) => url.endsWith("skip")
    ? fail ? { ok: false, status: 409, json: async () => ({ detail: "The demo is already past 65′." }) }
      : { ok: true, status: 200, json: async () => ({ skipped_seconds: 1200, target: { label: "+20′" } }) }
    : { ok: true, status: 200, json: async () => ({ points: [], live: true, runs: [{ match_id: "m1" }], skips: [{ id: "20", label: "+20′" }] }) });
  await showSkip(document, "m1", api, { overlay, clock: () => 2700 });
  targets.children[0]!.listeners.click!();
  await new Promise((done) => setTimeout(done, 0));
  assert.deepEqual([overlay.up, overlay.target, nodes.get("match-skip-title")!.textContent], [true, 3900, "Skipping ahead to 65′"]);
  clock.fire();
  await new Promise((done) => setTimeout(done, 0));
  assert.equal(nodes.get("match-skip-note")!.textContent, "Still catching up; the clock will settle shortly.");
  fail = true;
  targets.children[0]!.listeners.click!();
  await new Promise((done) => setTimeout(done, 0));
  assert.deepEqual([overlay.up, nodes.get("match-skip-note")!.textContent], [false, "The demo is already past 65′."]);
});

test("a target's label guesses the seconds ahead until the operator answers", () => {
  assert.equal(labelSeconds("+20′", 2700), 1200);  // relative
  assert.equal(labelSeconds("65′", 2700), 1200);  // a point on the clock
  assert.equal(labelSeconds("65′", 4000), null);  // already past it
  assert.equal(labelSeconds("Half-time", 0), null);
});

test("the picker shows a live demo match's clock from its feed run, not the lagging backend watermark", () => {
  const now = Date.parse("2026-10-26T15:10:00Z");
  const matches = [{ match_id: "a", status: "live", clock_seconds: 100 }, { match_id: "b", status: "live", clock_seconds: 200 },
    { match_id: "c", status: "scheduled", clock_seconds: null }, { match_id: "d", status: "live", clock_seconds: 300 }];
  const runs = [{ match_id: "a", kickoff: "2026-10-26T15:00:00Z" }, { match_id: "c", kickoff: "2026-10-26T15:20:00Z" },
    { match_id: "d", kickoff: "not a date" }];
  assert.deepEqual(withRunClocks(matches, runs, now).map((m) => m.clock_seconds), [600, 200, null, 300]);
  assert.deepEqual(withRunClocks([{ match_id: "c", status: "live", clock_seconds: 5 }], runs, now)[0]!.clock_seconds, 0);  // clamped
  const { document } = doc();
  const controls = new DemoControls(document, stub<DemoApi>({}));
  controls.render({ live: true, points: [], runs: [{ match_id: "a", kickoff: "2026-10-26T15:00:00Z" }] });
  assert.deepEqual(controls.feedRuns, [{ match_id: "a", kickoff: "2026-10-26T15:00:00Z" }]);
  controls.render({ live: false, points: [], runs: [{ match_id: "a" }] });
  assert.deepEqual(controls.feedRuns, []);
});
