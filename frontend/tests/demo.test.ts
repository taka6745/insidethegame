import test from "node:test";
import assert from "node:assert/strict";
import { DemoApi, DemoControls, demoMatches, mainToOpen, showLiveFrom } from "../match/demo.ts";
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
  replaceChildren(...children: El[]) { this.children = children; }
  addEventListener() {}
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

test("while a demo is on the picker lists only its matches", () => {
  const matches = [{ match_id: "a", status: "live" }, { match_id: "b", status: "finished" }, { match_id: "c", status: "scheduled" }];
  assert.deepEqual(demoMatches(matches, true).map((m) => m.match_id), ["a", "c"]);
  assert.equal(demoMatches(matches, false).length, 3);
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

test("the audience bucket is fixed while the match is live", () => {
  const { document } = doc();
  const view = new AudienceView(document);
  view.connection(true);
  const buckets = [{ id: "x", label: "X" }, { id: "y", label: "Y" }];
  view.render(stub({ audience_buckets: buckets, match: { status: "scheduled" } }));
  assert.equal(view.select.disabled, false);
  view.render(stub({ audience_buckets: buckets, match: { status: "live" } }));
  assert.equal(view.select.disabled, true);
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

test("follow polls until every stage is ready, then hides", async () => {
  const seen: boolean[] = [];
  let calls = 0;
  const ok = await follow(async () => ({ live: true, matches: 3, stages: [{ id: "feed", ready: ++calls > 2 }] }),
    { render: (status) => { seen.push(status.stages[0]!.ready); return status.stages[0]!.ready; }, hide: () => seen.push(false) },
    { sleep: async () => {} });
  assert.equal(ok, true);
  assert.deepEqual(seen, [false, false, true, false]);
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
  assert.match(from.textContent ?? "", /generated earlier on this pipeline; live from 20′/);
  assert.equal(from.hidden, false);
  await showLiveFrom(document, "other", stub<DemoApi>({ state: async () => state }));
  assert.equal(from.hidden, true);
  await showLiveFrom(document, "m1", stub<DemoApi>({ state: async () => { throw new Error("no operator"); } }));
  assert.equal(from.hidden, true);
});
