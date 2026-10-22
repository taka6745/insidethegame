import test from "node:test";
import assert from "node:assert/strict";
import {
  currentSnapshot,
  latestEvents,
  clock,
  isLive,
  matchStatus,
} from "../match/format.ts";
import { ANSWERS_UNAVAILABLE, MatchController } from "../match/controller.ts";
import type { ControllerOptions } from "../match/controller.ts";
import { MatchApi } from "../match/api.ts";
import type { Fetcher } from "../match/api.ts";
import type { ChatSession, ServiceError, Snapshot, Timers } from "../match/types.ts";
import { deferred, stub } from "./support.ts";
const snapshot = (version = 1, run = "r"): Snapshot => ({
  type: "snapshot",
  version,
  match: { id: run },
  cards: [],
  events: [],
  narratives: [],
});
function fixture(api: object = {}) {
  const renders: Snapshot[] = [],
    chats: ChatSession[] = [],
    statuses: [string, boolean?][] = [],
    frames: (() => void)[] = [],
    storage = new Map<string, string>();
  const view = {
    render: (s: Snapshot) => renders.push(s),
    error() {},
    connection() {},
    audience: { setBusy() {}, render() {} },
  };
  const questions = {
    render: (s: ChatSession) => chats.push(s),
    status: (...s: [string, boolean?]) => statuses.push(s),
  };
  const live = { stop() {}, connect() {} };
  const controller = new MatchController(stub<ControllerOptions>({
    api,
    view,
    questions,
    live,
    storage: {
      getItem: (k: string) => storage.get(k),
      setItem: (k: string, v: string) => storage.set(k, v),
    },
    uuid: () => "uuid",
    schedule: (fn: () => void) => frames.push(fn),
  }));
  controller.profile = "one";
  controller.token = "t";
  controller.session = { turns: [], offers: [] };
  return { controller, renders, chats, statuses, frames };
}
test("state rejects out-of-order versions, accepts new runs and bounds retained lists", () => {
  const prior = snapshot(9);
  assert.equal(currentSnapshot(prior, snapshot(8)), prior);
  assert.equal(currentSnapshot(prior, { type: "heartbeat" }), prior);
  assert.equal(currentSnapshot(prior, snapshot(1, "new")).version, 1);
  const large = {
    ...snapshot(),
    events: Array(1000).fill({}),
    narratives: Array(1000).fill({}),
    cards: Array.from({ length: 100 }, (_, id) => ({ id })),
  };
  const limited = currentSnapshot(null, large)!;
  assert.equal(limited.events.length, 60);
  assert.equal(limited.narratives.length, 300);
  assert.deepEqual(limited.cards.map((card) => card.id), [0, 1, 2, 3, 4]);
});
test("many socket updates coalesce to latest state in one animation frame", () => {
  const f = fixture();
  for (let i = 1; i <= 100; i++) f.controller.receive(snapshot(i));
  assert.equal(f.frames.length, 1);
  f.frames[0]!();
  assert.equal(f.renders[0]!.version, 100);
});
test("late question response cannot replace new profile conversation", async () => {
  const pending = deferred();
  const f = fixture({
    ask: () => pending.promise,
    restore: async () => ({ turns: [{ prompt: "old" }] }),
  });
  const work = f.controller.send("old question");
  f.controller.generation++;
  pending.resolve({});
  await work;
  assert.equal(f.chats.length, 1); // only optimistic display before profile changed
});
test("failed question retries same request UUID and restores prompt", async () => {
  const calls: unknown[][] = [];
  const f = fixture({
    ask: async (...args: unknown[]) => {
      calls.push(args);
      throw new Error("offline");
    },
  });
  const restored: string[] = [];
  f.controller.onRetryPrompt = (prompt) => restored.push(prompt);
  await f.controller.send("How many shots?");
  await f.controller.send("How many shots?");
  assert.equal(calls[0]![2], calls[1]![2]);
  assert.equal(restored.length, 2);
});
test("a question carries the seq of the shown picture, not the newest received snapshot", async () => {
  const calls: unknown[][] = [];
  const f = fixture({ ask: async (...args: unknown[]) => { calls.push(args); }, restore: async () => ({ turns: [] }) });
  f.controller.shown = { ...snapshot(2), match: { seq: 140, clock_seconds: 600 } };
  f.controller.snapshot = { ...snapshot(3), match: { seq: 180, clock_seconds: 640 } };
  await f.controller.send("What just happened?");
  assert.equal(calls[0]![3], 140);
});
test("session takeover disables questions and invalidates pending responses", () => {
  const f = fixture();
  f.controller.connection("replaced");
  assert.equal(f.controller.token, null);
  assert.equal(f.controller.generation, 1);
  assert.equal(f.statuses.at(-1)![1], true);
});
test("late session creation cannot replace newer profile", async () => {
  const pending = deferred();
  const f = fixture({ session: () => pending.promise });
  const work = f.controller.connect();
  f.controller.generation++;
  pending.resolve({ session_token: "old" });
  await work;
  assert.equal(f.controller.token, null);
});
test("clock ordering ignores late corrections and feed omits tombstones", () => {
  const events = [
    { event_id: "new", match_time_seconds: 300 },
    { event_id: "old", match_time_seconds: 20 },
    { event_id: "deleted", match_time_seconds: 1000, deleted: true },
  ];
  assert.equal(latestEvents(events)[0]!.event_id, "new");
  assert.equal(latestEvents(events).length, 2);
  assert.equal(clock(null), "PRE-MATCH");
});
test("HTTP adapter only sends intent, token and offer identifiers", async () => {
  const calls: Parameters<Fetcher>[] = [];
  const api = new MatchApi(async (...args) => {
    calls.push(args);
    return { ok: true, status: 200, json: async () => ({}) };
  }, "/viewer-api", "chelsea-united-1a2b3c4d");
  await api.ask("token", "shots?", "uuid");
  await api.track("token", "offer");
  await api.unpin("token", "rule");
  assert.deepEqual(JSON.parse(String(calls[0]![1].body)), {
    prompt: "shots?",
    request_id: "uuid",
  });
  await api.ask("token", "shots?", "uuid2", 42);
  assert.deepEqual(JSON.parse(String(calls.pop()![1].body)), { prompt: "shots?", request_id: "uuid2", seq: 42 });
  await api.prices();
  assert.equal(calls.pop()![0], "/viewer-api/prices");
  assert.deepEqual(JSON.parse(String(calls[1]![1].body)), {});
  assert.equal(calls[2]![1].method, "DELETE");
  const M = "/viewer-api/matches/chelsea-united-1a2b3c4d/sessions";
  assert.deepEqual(calls.map(([url]) => url),
    [`${M}/token/messages`, `${M}/token/offers/offer/track`, `${M}/token/pins/rule`]);
  assert.equal(
    api.socketUrl("t", { protocol: "https:", host: "match.example" }),
    `wss://match.example${M}/t/live`,
  );
  await api.session("one");
  await api.matches();
  assert.equal(calls[3]![0], M);
  assert.equal(calls[4]![0], "/viewer-api/matches");
});

test("audience choices update the same session without replacing chat or pins", async () => {
  const selection = {bucket_id: "neutral:experienced"};
  const updated = {...snapshot(2), audience: selection, cards: [{id:"pinned"}]};
  const f = fixture({audience: async (token: string, body: unknown) => {
    assert.equal(token, "t");
    assert.deepEqual(body, selection);
    return {snapshot: updated};
  }});
  f.controller.session = {turns: [{prompt: "earlier question"}], offers: [{id:"saved"}]};
  const session = f.controller.session;
  await f.controller.selectAudience(selection);
  assert.equal(f.controller.token, "t");
  assert.equal(f.controller.session, session);
  assert.equal(f.chats.length, 0);
  assert.deepEqual(f.controller.snapshot!.audience, selection);
  assert.equal(f.controller.snapshot!.cards[0]!.id, "pinned");
  assert.equal(f.controller.audienceBusy, false);
});

test("failed audience save restores the committed choice", async () => {
  const f = fixture({audience: async () => {throw new Error("offline");}});
  f.controller.snapshot = {...snapshot(), audience:{bucket_id:"home:simple"}};
  let restored;
  f.controller.view.audience.render = value => { restored = value; };
  await f.controller.selectAudience({bucket_id:"away:casual"});
  assert.equal(restored, f.controller.snapshot);
  assert.equal(f.controller.audienceBusy, false);
});

test("a late audience save cannot update a replacement session", async () => {
  const pending = deferred();
  const f = fixture({audience: () => pending.promise});
  const work = f.controller.selectAudience({bucket_id:"away:casual"});
  f.controller.generation++;
  pending.resolve({snapshot:snapshot(5)});
  await work;
  assert.equal(f.controller.snapshot, null);
});

test("audience API sends the chosen bucket id without profile or config writes", async () => {
  const selection = {bucket_id:"away:casual"};
  const api = new MatchApi(async (url, options) => {
    assert.equal(url, "/viewer-api/matches/m1/sessions/token/audience");
    assert.equal(options.method, "PUT");
    assert.deepEqual(JSON.parse(String(options.body)), selection);
    return {ok:true,status:200,json:async () => ({})};
  }, "/viewer-api", "m1");
  await api.audience("token",selection);
});

test("HTML proxy failures preserve status and give an actionable retry message", async () => {
  const api = new MatchApi(async () => new Response('<html>Bad Gateway</html>', {status: 502}));
  await assert.rejects(api.profiles(), (error: ServiceError) => {
    assert.equal(error.status, 502);
    assert.match(error.message, /temporarily unavailable.*try again/i);
    assert.doesNotMatch(error.message, /html|unreadable/i);
    return true;
  });
});

test("malformed successful responses remain errors", async () => {
  const api = new MatchApi(async () => new Response('broken', {status: 200}));
  await assert.rejects(api.profiles(), /invalid response/i);
});

test("restored pending answer refreshes only while pending and stops after completion", async () => {
  const f = fixture({
    restore: async () => ({
      turns: [{ status: "complete", reply: { text: "Two shots." } }],
    }),
  });
  const timers = new Map<number, () => Promise<void>>();
  let id = 0;
  f.controller.timers = stub<Timers>({
    setTimeout(fn: () => Promise<void>) {
      timers.set(++id, fn);
      return id;
    },
    clearTimeout(key: number) {
      timers.delete(key);
    },
  });
  f.controller.showChat({ turns: [{ status: "pending" }] });
  assert.equal(timers.size, 1);
  await [...timers.values()][0]!();
  assert.equal(f.chats.at(-1)!.turns![0]!.reply!.text, "Two shots.");
  assert.equal(timers.size, 0);
});

test("default HTTP fetch retains browser global receiver", async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = stub<typeof fetch>(async function (this: unknown) {
    assert.equal(this, globalThis);
    return { ok: true, json: async () => ({ profiles: [] }) };
  });
  try {
    await new MatchApi().profiles();
  } finally {
    globalThis.fetch = previous;
  }
});
test("explicit reconnect retries profiles when initial discovery failed", async () => {
  const f = fixture({
    profiles: async () => ({ profiles: [{ id: "one" }] }),
    session: async () => ({
      session_token: "t",
      turns: [],
      snapshot: snapshot(),
    }),
    socketUrl: () => "ws://local",
  });
  f.controller.profile = null;
  await f.controller.connect();
  assert.equal(f.controller.profile, "one");
  assert.equal(f.controller.token, "t");
});
test("second half events supersede first half stoppage despite overlapping clocks", () => {
  const rows = [
    { event_id: "stoppage", period: 1, match_time_seconds: 2880 },
    { event_id: "restart", period: 2, match_time_seconds: 2730 },
  ];
  assert.equal(latestEvents(rows)[0]!.event_id, "restart");
});

test("sessions are stored per match; a stale token falls back to a new session", async () => {
  const calls: string[] = [];
  const f = fixture({
    match: "m1",
    restore: async () => { calls.push("restore"); throw Object.assign(new Error("Unknown session"), { status: 404 }); },
    session: async () => { calls.push("session"); return { session_token: "fresh", turns: [], snapshot: snapshot() }; },
    socketUrl: () => "ws://local",
  });
  f.controller.storage.setItem("match-session:m1:one", "old");
  f.controller.storage.setItem("match-session:m2:one", "other");
  await f.controller.connect({ restore: true });
  assert.deepEqual(calls, ["restore", "session"]);
  assert.equal(f.controller.token, "fresh");
  assert.equal(f.controller.storage.getItem("match-session:m1:one"), "fresh");
  assert.equal(f.controller.storage.getItem("match-session:m2:one"), "other");
});

test("opening the page resumes this tab's session; only Reconnect starts a new one", async () => {
  const calls: string[] = [];
  const f = fixture({
    match: "m1",
    profiles: async () => ({ profiles: [{ id: "one" }] }),
    restore: async (token: string) => { calls.push(`restore:${token}`); return { session_token: token, turns: [], snapshot: snapshot() }; },
    session: async () => { calls.push("session"); return { session_token: "fresh", turns: [], snapshot: snapshot() }; },
    socketUrl: () => "ws://local",
  });
  f.controller.storage.setItem("match-session:m1:one", "mine");
  await f.controller.start();
  assert.deepEqual(calls, ["restore:mine"]);
  assert.equal(f.controller.token, "mine");
  await f.controller.connect();
  assert.deepEqual(calls, ["restore:mine", "session"]);
});

test("a resuming tab's retry while its match details load keeps its own session", async () => {
  const calls: string[] = [], timers: (() => void)[] = [];
  const f = fixture({
    match: "m1",
    profiles: async () => ({ profiles: [{ id: "one" }] }),
    restore: async (token: string) => {
      calls.push(`restore:${token}`);
      if (calls.length < 2) throw Object.assign(new Error("Not available yet"), { status: 503, code: "snapshot_unavailable" });
      return { session_token: token, turns: [], snapshot: snapshot() };
    },
    session: async () => { calls.push("session"); return { session_token: "fresh", turns: [], snapshot: snapshot() }; },
    socketUrl: () => "ws://local",
  });
  f.controller.timers = stub<Timers>({ setTimeout: (fn: () => void) => timers.push(fn), clearTimeout() {} });
  f.controller.storage.setItem("match-session:m1:one", "mine");
  await f.controller.start();
  timers.shift()!();
  await new Promise((done) => setImmediate(done));
  assert.deepEqual(calls, ["restore:mine", "restore:mine"]);
  assert.equal(f.controller.token, "mine");
});

test("a purged or unknown match (404) stops the viewer and returns to the picker", async () => {
  let gone = 0, stopped = 0;
  const f = fixture({
    match: "m1",
    session: async () => { throw Object.assign(new Error("Match not found"), { status: 404 }); },
  });
  f.controller.onGone = () => gone++;
  f.controller.live.stop = () => stopped++;
  await f.controller.connect();
  assert.equal(gone, 1);
  assert.ok(stopped >= 1);
  assert.equal(f.controller.token, null);
  f.controller.token = "t";
  f.controller.connection("gone");
  assert.equal(gone, 2);
  assert.equal(f.controller.token, null);
});

test("a match linked before it opens waits and retries instead of leaving for the picker", async () => {
  let gone = 0, attempts = 0, opened = 0;
  const states: string[] = [], timers: (() => void)[] = [];
  const f = fixture({
    match: "m1",
    session: async () => {
      if (++attempts < 2)
        throw Object.assign(new Error("Not open yet"), { status: 404, code: "match_not_started" });
      if (attempts < 3) // Opened, but its details are not served yet.
        throw Object.assign(new Error("Not available yet"), { status: 503, code: "snapshot_unavailable" });
      return { session_token: "fresh", turns: [], snapshot: { ...snapshot(), match: { id: "m1", status: "scheduled" } } };
    },
    socketUrl: () => "ws://local",
  });
  f.controller.onGone = () => gone++;
  f.controller.onOpened = () => opened++;
  f.controller.view.connection = (state) => states.push(state);
  f.controller.timers = stub<Timers>({ setTimeout: (fn: () => void) => timers.push(fn), clearTimeout() {} });
  await f.controller.connect();
  assert.equal(states.at(-1), "waiting");
  assert.equal(timers.length, 1);
  timers.shift()!();
  await new Promise((done) => setImmediate(done));
  assert.equal(states.at(-1), "connecting");
  assert.equal(timers.length, 1);
  timers.shift()!();
  await new Promise((done) => setImmediate(done));
  assert.equal(attempts, 3);
  assert.equal(f.controller.token, "fresh");
  assert.equal(gone, 0);
  assert.equal(opened, 1);
  // A retry left over from before a reconnect does nothing.
  f.controller.wait(f.controller.generation - 1);
  timers.shift()!();
  assert.equal(attempts, 3);
});

test("untrack revision wins over delayed pinned frames and conflicting equal versions", () => {
  const f = fixture();
  const pinned = {
    ...snapshot(30),
    projection_epoch: "owner",
    cards: [{ id: "custom", kind: "custom" }],
  };
  const unpinned = {
    ...snapshot(31),
    projection_epoch: "owner",
    cards: [{ id: "default", kind: "standard" }],
  };
  f.controller.receive(pinned);
  f.controller.receive(unpinned);
  f.controller.receive(pinned);
  f.controller.receive({ ...pinned, version: 31 });
  f.frames[0]!();
  assert.equal(f.renders.at(-1)!.cards[0]!.id, "default");
});
test("new projection epoch accepts lower version for the same persistent run", () => {
  const prior = { ...snapshot(30), projection_epoch: "old-owner" };
  const restarted = { ...snapshot(1), projection_epoch: "new-owner" };
  assert.equal(currentSnapshot(prior, restarted).projection_epoch, "new-owner");
});
test("a late HTTP snapshot cannot restore a retired projection epoch after reconnect", () => {
  const f = fixture();
  f.controller.receive({ ...snapshot(30), projection_epoch: "old-owner" });
  f.controller.receive({ ...snapshot(1), projection_epoch: "new-owner" });
  f.controller.receive({ ...snapshot(31), projection_epoch: "old-owner" });
  f.frames[0]!();
  assert.equal(f.renders.at(-1)!.projection_epoch, "new-owner");
});

test("live and finished phases accept the multi-match and older status names", () => {
  assert.ok(isLive("live") && !isLive("scheduled") && !isLive("finished"));
  assert.equal(matchStatus({ status: "live", clock_seconds: 431 }), "Live · 7:11");
  assert.equal(matchStatus({ status: "finished" }), "Full time");
  assert.match(matchStatus({ status: "scheduled", scheduled_kickoff: "2026-10-20T15:00:00Z" }, "en-GB"), /^Kick-off \d\d:\d\d$/);
  assert.equal(matchStatus({ status: "scheduled", scheduled_kickoff: null }), "Scheduled");
});

test("live states render only once the live picture reaches their producer time", () => {
  const f = fixture();
  let playhead: number | null = 10, now = 0;
  const timers: (() => void)[] = [];
  f.controller.playhead = () => playhead;
  f.controller.now = () => now;
  f.controller.timers = stub<Timers>({ setTimeout: (fn: () => void) => timers.push(fn), clearTimeout() {} });
  const live = (version: number, seconds: number): Snapshot =>
    ({ ...snapshot(version), match: { id: "r", media: { url: "/media/hls/r/live.m3u8", seconds } } });
  f.controller.receive(live(1, 9));
  f.controller.receive(live(2, 12));
  f.frames.shift()!();
  assert.deepEqual(f.renders.map((s) => s.version), [1]);
  assert.equal(f.controller.snapshot!.version, 2); // newest state stays authoritative for questions
  assert.equal(timers.length, 1);
  playhead = 12;
  timers.shift()!();
  f.frames.shift()!();
  assert.deepEqual(f.renders.map((s) => s.version), [1, 2]);
  assert.equal(timers.length, 0);
  f.controller.receive(live(3, 40));
  f.frames.shift()!();
  now = 15000;
  timers.shift()!();
  f.frames.shift()!();
  assert.deepEqual(f.renders.map((s) => s.version), [1, 2, 3]);
  playhead = null;
  f.controller.receive(live(4, 99));
  f.frames.shift()!();
  assert.equal(f.renders.at(-1)!.version, 4);
});

test("clarification choice sends a normal message on the current session and respects busy state", async () => {
  const calls: unknown[][] = [];
  const pending = deferred();
  const f = fixture({ ask: (...args: unknown[]) => { calls.push(args); return pending.promise; },
    restore: async () => ({ turns: [], session_token: "t" }),
  });
  const send = f.controller.questions.onClarify!("Headed shots");
  f.controller.questions.onClarify!("Headed passes");
  // Nothing shown yet: the answer is bounded to kick-off, never the newest held state.
  assert.deepEqual(calls, [["t", "Headed shots", "uuid", 0]]);
  pending.resolve({});
  await send;
  f.controller.connection("replaced");
  await f.controller.questions.onClarify!("Headed passes");
  assert.equal(calls.length, 1);
});

test("session replaced response to a clarification locks chat even before socket notification", async () => {
  const f = fixture({ ask: async () => { throw Object.assign(new Error("Session ended"), { code: "session_replaced" }); } });
  await f.controller.questions.onClarify!("Headed shots");
  assert.equal(f.controller.token, null);
  assert.equal(f.statuses.at(-1)![1], true);
});

test("an audience change re-frames the shown and held states now, without insights ahead of the picture", async () => {
  const at = (version: number, clock: number, bucket: string): Snapshot => ({
    ...snapshot(version), bucket_id: bucket,
    match: { id: "r", period: 1, clock_seconds: clock, media: { url: "/media/hls/r/live.m3u8", seconds: clock } },
    narratives: [{ id: `${bucket}:60`, period: 1, clock_seconds: 60 }, { id: `${bucket}:${clock}`, period: 1, clock_seconds: clock }],
  });
  const f = fixture({ audience: async () => ({ snapshot: at(3, 120, "away:simple") }) });
  let playhead: number | null = 60;
  f.controller.playhead = () => playhead;
  f.controller.timers = stub<Timers>({ setTimeout: () => null, clearTimeout() {} });
  f.controller.receive(at(1, 60, "home:simple"));
  f.controller.receive(at(2, 90, "home:simple"));
  f.frames.shift()!();
  await f.controller.selectAudience({ bucket_id: "away:simple" });
  const now = f.renders.at(-1)!;
  assert.equal(now.version, 1);
  assert.equal(now.bucket_id, "away:simple");
  assert.deepEqual(now.narratives.map((n) => n.id), ["away:simple:60"]);
  playhead = 90;
  f.frames.shift()!();
  const held = f.renders.at(-1)!;
  assert.equal(held.version, 2);
  assert.deepEqual(held.narratives.map((n) => n.id), ["away:simple:60"]); // never the old bucket again
});

test("without a model the viewer says answers are unavailable and disables asking", async () => {
  const f = fixture({
    ask: async () => { throw Object.assign(new Error("Questions are unavailable"), { status: 503, code: "model_unavailable" }); },
  });
  f.controller.showChat({ mode: "unavailable", turns: [], offers: [] });
  assert.deepEqual(f.statuses.at(-1), [ANSWERS_UNAVAILABLE, true]);
  f.controller.showChat({ mode: "local", turns: [], offers: [] });
  await f.controller.send("How many shots?");
  assert.deepEqual(f.statuses.at(-1), [ANSWERS_UNAVAILABLE, true]);
  assert.equal(f.controller.retry, null);
  assert.equal(f.controller.busy, false);
});

test("questions wait longer than the backend's 240 s budget; other calls keep 75 s", async () => {
  const { QUESTION_TIMEOUT_MS } = await import("../match/api.ts");
  assert.ok(QUESTION_TIMEOUT_MS >= 250_000);
  const original = AbortSignal.timeout;
  const asked: number[] = [];
  AbortSignal.timeout = (ms: number) => { asked.push(ms); return original.call(AbortSignal, ms); };
  try {
    const api = new MatchApi(async () => ({ ok: true, status: 200, json: async () => ({}) }), "/viewer-api", "m1");
    await api.ask("t", "shots?", "uuid");
    await api.restore("t");
  } finally { AbortSignal.timeout = original; }
  assert.deepEqual(asked, [QUESTION_TIMEOUT_MS, 75000]);
});
