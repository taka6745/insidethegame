import test from "node:test";
import assert from "node:assert/strict";
import { queueStill, ReplayStage, replayStill } from "../match/replay-view.ts";
import type { StreamOptions } from "../match/media.ts";
import type { Replay } from "../match/types.ts";
import { stub } from "./support.ts";

class Style extends Object {
  [name: string]: unknown;
  setProperty(name: string, value: string) { this[name] = value; }
}
class Element {
  [attribute: string]: unknown;
  hidden = true;
  disabled = false;
  paused = true;
  muted = false;
  currentTime = 0;
  textContent = "";
  focused = false;
  dataset: Record<string, string> = {};
  style = new Style() as Style & Record<string, string>;
  children: Element[] = [];
  parent: Element | null = null;
  listeners: Record<string, ((event?: unknown) => void)[]> = {};
  addEventListener(name: string, fn: (event?: unknown) => void) { (this.listeners[name] ||= []).push(fn); }
  emit(name: string, event?: unknown) { for (const fn of this.listeners[name] || []) fn(event); }
  setAttribute(name: string, value: unknown) { this[name] = value; }
  getAttribute(name: string) { return (this[name] as string | undefined) ?? null; }
  removeAttribute(name: string) { delete this[name]; }
  replaceChildren(...children: Element[]) { this.children = children; for (const c of children) c.parent = this; }
  get isConnected() { return true; }
  focus() { this.focused = true; }
  async play() { this.paused = false; this.emit("play"); }
  pause() { this.paused = true; this.emit("pause"); }
}
function setup(options: { reducedMotion?: boolean } = {}) {
  const nodes = new Map<string, Element>();
  const document = Object.assign(new Element(), {
    getElementById(id: string): Element {
      if (!nodes.has(id)) nodes.set(id, new Element());
      return nodes.get(id)!;
    },
    createElement: () => new Element(),
  });
  const streams: { url: string; options: StreamOptions; destroyed: boolean }[] = [];
  const timers: { run: () => void; ms: number; id: number }[] = [];
  let ids = 0;
  const stage = new ReplayStage(stub<Document>(document), {
    reducedMotion: () => Boolean(options.reducedMotion),
    timers: {
      set: (run, ms) => { timers.push({ run, ms, id: ++ids }); return ids; },
      clear: (id) => { const at = timers.findIndex((t) => t.id === id); if (at >= 0) timers.splice(at, 1); },
    },
    attach: async (_video, url, options) => {
      const stream = { url, options, destroyed: false };
      streams.push(stream);
      return { destroy: () => { stream.destroyed = true; } };
    },
  });
  const get = (id: string) => document.getElementById(id);
  const fire = () => { const timer = timers.shift()!; timer.run(); return timer.ms; };
  return { stage, document, get, streams, timers, fire };
}
const replay: Replay = {
  page: 0, page_size: 12, total_items: 2, seconds: 20, playlist: "/media/hls/m1/live.m3u8",
  clips: [
    { start: 100, end: 110, captions: ["23′ Ashworth header saved"], playlist_start: 1, playlist_end: 11, marks: [106] },
    { start: 200, end: 210, captions: ["31′ Goal"], playlist_start: 14, playlist_end: 24 },
  ],
};

test("Play moves the replay to the stage, live becomes the corner picture, Back to live restores it", async () => {
  const { stage, get, streams } = setup();
  const opener = new Element();
  stage.open(replay, stub<HTMLElement>(opener));
  await Promise.resolve();
  assert.equal(get("match-stage").dataset.mode, "replay");
  assert.equal(get("replay-video").hidden, false);
  assert.equal(get("pip-return").hidden, false);
  assert.equal(get("replay-video").muted, true);
  assert.equal(streams[0]!.url, "/media/hls/m1/live.m3u8");
  assert.deepEqual(streams[0]!.options.start, 1);
  assert.equal(get("replay-caption").textContent, "1/2 · 23′ Ashworth header saved");
  assert.equal(get("replay-close").focused, true);
  assert.equal(get("replay-badge").textContent, "Replay 1/2");
  // One bar for the reel (two 10 s clips): the clip join at 50%, the event at 106 s at 30%.
  assert.deepEqual(get("replay-marks").children.map((c) => [c.className, c.style.left]),
    [["replay-join", "50%"], ["replay-mark", "30%"]]);
  get("replay-video").currentTime = 6;
  get("replay-video").emit("timeupdate");
  assert.equal(get("replay-progress-fill").style.width, "25%");
  get("pip-return").emit("click");
  assert.equal(get("match-stage").dataset.mode, "live");
  assert.equal(get("replay-video").hidden, true);
  assert.equal(get("replay-overlay").hidden, true);
  assert.equal(streams[0]!.destroyed, true);
  assert.equal(opener.focused, true);
});

test("the replay advances clips on time updates, pauses after the last clip and Esc closes it", async () => {
  const { stage, document, get } = setup();
  stage.open(replay);
  await Promise.resolve();
  const video = get("replay-video");
  video.currentTime = 11;
  video.emit("timeupdate");
  assert.equal(video.currentTime, 14);
  assert.equal(get("replay-caption").textContent, "2/2 · 31′ Goal");
  video.emit("click");
  assert.equal(video.paused, true);
  video.emit("click");
  assert.equal(video.paused, false);
  video.currentTime = 24;
  video.emit("timeupdate");
  assert.equal(video.paused, true);
  assert.equal(get("replay-caption").textContent, "Replay finished");
  // The last frame holds, greyed, with Replay and Back to live.
  assert.equal(get("match-stage").dataset.ended, "true");
  assert.equal(get("replay-end").hidden, false);
  assert.equal(get("replay-close").hidden, true);
  assert.equal(get("replay-again").focused, true);
  get("replay-again").emit("click");
  assert.equal(video.currentTime, 1);
  assert.equal(get("match-stage").dataset.ended, "false");
  assert.equal(get("replay-badge").textContent, "Replay 1/2");
  document.emit("keydown", { key: "Escape" });
  assert.equal(stage.isOpen, false);
  assert.equal(get("match-video").focused, true);
});

test("a replay without footage never takes over the stage", () => {
  const { stage, get, streams } = setup();
  stage.open({ ...replay, playlist: null });
  assert.equal(stage.isOpen, false);
  assert.equal(get("match-stage").dataset.mode, undefined);
  assert.deepEqual(streams, []);
});


test("chat stills draw the middle of the first clip of the published stream and release the player", async () => {
  const drawn: unknown[] = [];
  let video: Element | null = null, destroyed = false;
  const canvas = {
    width: 0, height: 0,
    ownerDocument: { createElement: () => (video = Object.assign(new Element(), { videoWidth: 1280, videoHeight: 720 })) },
    getContext: () => ({ drawImage: (...args: unknown[]) => drawn.push(args) }),
  };
  const done = replayStill(replay, stub<HTMLCanvasElement>(canvas), {
    attach: async (_video, url, options) => {
      assert.equal(url, "/media/hls/m1/live.m3u8");
      assert.equal(options.start, 6);
      return { destroy: () => { destroyed = true; } };
    },
  });
  await Promise.resolve();
  video!.emit("loadeddata");
  assert.equal(video!.currentTime, 6);
  video!.emit("seeked");
  assert.equal(await done, true);
  assert.equal(drawn.length, 1);
  assert.deepEqual([canvas.width, canvas.height], [1280, 720]);
  assert.equal(destroyed, true);
});


test("a published-stream replay seeks match video times", async () => {
  const { stage, streams } = setup();
  stage.open({ ...replay, playlist: "/media/hls/m1/live.m3u8",
    clips: replay.clips.map((clip) => ({ ...clip, playlist_start: clip.start, playlist_end: clip.end })) });
  await Promise.resolve();
  assert.equal(streams[0]!.url, "/media/hls/m1/live.m3u8");
  assert.equal(streams[0]!.options.start, 100);
});


test("media recovery reloading metadata does not restart the clip", async () => {
  const { stage, get } = setup();
  stage.open(replay);
  await Promise.resolve();
  const video = get("replay-video");
  video.emit("loadedmetadata");
  assert.equal(video.currentTime, 1);
  video.currentTime = 7;
  video.emit("loadedmetadata");
  assert.equal(video.currentTime, 7);
});

test("stills draw one at a time, only once their card is visible", async () => {
  const observed: ((entries: { isIntersecting: boolean }[]) => void)[] = [];
  const original = globalThis.IntersectionObserver;
  globalThis.IntersectionObserver = stub<typeof IntersectionObserver>(class {
    constructor(fn: (entries: { isIntersecting: boolean }[]) => void) { observed.push(fn); }
    observe() {}
    disconnect() {}
  });
  try {
    const order: string[] = [];
    let release = () => {};
    const tick = () => new Promise((r) => setTimeout(r, 0));
    queueStill(stub<HTMLCanvasElement>({}), () => { order.push("a"); return new Promise<void>((r) => { release = r; }); });
    queueStill(stub<HTMLCanvasElement>({}), async () => { order.push("b"); });
    await tick();
    assert.deepEqual(order, []);  // Nothing is visible yet.
    observed[0]!([{ isIntersecting: false }]);
    observed[0]!([{ isIntersecting: true }]);
    observed[1]!([{ isIntersecting: true }]);
    await tick();
    assert.deepEqual(order, ["a"]);  // b waits for a's decoder.
    release();
    await tick();
    assert.deepEqual(order, ["a", "b"]);
  } finally {
    globalThis.IntersectionObserver = original;
  }
});

test("between clips the stage pauses, fades the sting in, cuts under it and fades it out over the next clip", async () => {
  const { stage, get, timers, fire } = setup();
  stage.open({ ...replay, playback: {
    transitions: { enabled: true, hold_seconds: 0.6, asset: "/assets/league/sting/replay-sting.mp4", asset_start_seconds: 0.15,
      sting_seconds: 2.4, cut_seconds: 0.5, fade_seconds: 0.3 },
    slow_motion: { enabled: true, rate: 0.5, ramp_seconds: 1, before_seconds: 1, after_seconds: 2 },
  } });
  await Promise.resolve();
  const video = get("replay-video"), sting = get("replay-sting"), clip = get("replay-sting-video");
  assert.equal(clip.src, "/assets/league/sting/replay-sting.mp4");  // cued when the reel opens
  assert.equal(sting.style["--sting-fade"], "0.3s");
  video.paused = false;
  video.currentTime = 7; video.playbackRate = 1;
  video.emit("timeupdate");
  assert.equal(video.playbackRate, 0.5);  // slow motion at the clip's event (106 s → 7 s)
  video.currentTime = 11;
  video.emit("timeupdate");
  assert.equal(video.paused, true);  // hold on the last frame
  assert.equal(sting.hidden, true);
  assert.equal(fire(), 600);
  assert.equal(sting.hidden, false);
  assert.equal(sting.dataset.state, "in");
  assert.equal(clip.currentTime, 0.15);
  assert.equal(clip.paused, false);
  assert.equal(fire(), 500);  // the cut, under the sting
  assert.equal(video.currentTime, 14);
  assert.equal(video.paused, true);
  assert.equal(get("replay-badge").textContent, "Replay 2/2");
  assert.equal(fire(), 1600);
  assert.equal(video.paused, false);  // the next clip plays as the sting fades
  assert.equal(sting.dataset.state, "out");
  video.emit("timeupdate");  // time updates during the fade leave it alone
  assert.equal(sting.dataset.state, "out");
  assert.equal(fire(), 300);
  assert.equal(sting.hidden, true);
  assert.equal(clip.paused, true);
  assert.equal(timers.length, 0);
});

test("the league's built-in sting draws in the page, loads no video and keeps the same timing", async () => {
  const { stage, get, timers, fire } = setup();
  stage.open({ ...replay, playback: {
    transitions: { enabled: true, hold_seconds: 0.6, asset: "builtin:league", asset_start_seconds: 0,
      sting_seconds: 2.4, cut_seconds: 0.5, fade_seconds: 0.3 },
    slow_motion: { enabled: false, rate: 0.5, ramp_seconds: 1, before_seconds: 1, after_seconds: 2 },
  } });
  await Promise.resolve();
  const video = get("replay-video"), sting = get("replay-sting"), clip = get("replay-sting-video");
  assert.equal(clip.src, undefined);  // no video asset is loaded
  assert.equal(sting.dataset.kind, "builtin");
  assert.equal(sting.style["--sting-length"], "2.4s");
  video.paused = false;
  video.currentTime = 11;
  video.emit("timeupdate");
  assert.equal(fire(), 600);
  assert.equal(sting.hidden, false);
  assert.equal(sting.dataset.state, "in");
  assert.equal(clip.paused, true);  // the video element stays idle
  assert.equal(fire(), 500);
  assert.equal(video.currentTime, 14);
  assert.equal(fire(), 1600);
  assert.equal(sting.dataset.state, "out");
  assert.equal(fire(), 300);
  assert.equal(sting.hidden, true);
  assert.equal(timers.length, 0);
});

test("reduced motion: the stage holds and cuts, with no sting and no slow motion; closing clears timers", async () => {
  const { stage, get, timers, fire } = setup({ reducedMotion: true });
  stage.open({ ...replay, playback: {
    transitions: { enabled: true, hold_seconds: 0.6, asset: "/assets/league/sting/replay-sting.mp4", asset_start_seconds: 0,
      sting_seconds: 2, cut_seconds: 0.5, fade_seconds: 0.3 },
    slow_motion: { enabled: true, rate: 0.5, ramp_seconds: 1, before_seconds: 1, after_seconds: 2 },
  } });
  await Promise.resolve();
  const video = get("replay-video");
  assert.equal(get("replay-sting-video").src, undefined);  // never loaded
  video.currentTime = 7; video.playbackRate = 1;
  video.emit("timeupdate");
  assert.equal(video.playbackRate, 1);
  video.currentTime = 11;
  video.emit("timeupdate");
  assert.equal(fire(), 600);
  assert.equal(video.currentTime, 14);
  assert.equal(get("replay-sting").hidden, true);
  video.currentTime = 24;
  video.emit("timeupdate");
  assert.equal(get("replay-end").hidden, false);  // last clip: no hold, the reel ends
  stage.open(replay);
  get("replay-video").currentTime = 11;
  get("replay-video").emit("timeupdate");
  stage.close();
  assert.equal(timers.length, 0);
});

test("footage ending early moves on a clip, a broken sting is skipped, closing restores the rate and focus follows", async () => {
  const { stage, get, timers, fire } = setup();
  stage.open({ ...replay, playback: {
    transitions: { enabled: true, hold_seconds: 0.6, asset: "/assets/league/sting/replay-sting.mp4", asset_start_seconds: 0,
      sting_seconds: 2.4, cut_seconds: 0.5, fade_seconds: 0.3 },
    slow_motion: { enabled: true, rate: 0.5, ramp_seconds: 1, before_seconds: 1, after_seconds: 2 },
  } });
  await Promise.resolve();
  const video = get("replay-video");
  video.currentTime = 9.5;
  video.emit("ended");  // short of the out point (11 s)
  assert.equal(stage.player!.phase, "holding");
  get("replay-sting-video").error = { code: 4 };
  fire();
  assert.equal(get("replay-sting").hidden, true);
  assert.equal(video.currentTime, 14);
  assert.equal(stage.player!.phase, "playing");
  assert.equal(timers.length, 0);
  video.currentTime = 24;
  video.emit("ended");
  assert.equal(get("replay-again").focused, true);
  get("replay-close").focused = false;
  get("replay-again").emit("click");
  assert.equal(get("replay-close").focused, true);  // the hidden Replay again hands focus back
  video.currentTime = 7;
  video.emit("timeupdate");
  assert.equal(video.playbackRate, 0.5);
  stage.close();
  assert.equal(video.playbackRate, 1);
});

test("a reel across matches switches streams between clips, under the sting, and ignores the old stream's time", async () => {
  const { stage, get, streams, fire } = setup();
  const other = { id: "m2", teams: [{ name: "North FC" }, { name: "South United" }] };
  stage.open({ ...replay, playlist: null, clips: [
    { ...replay.clips[0]!, playlist: "/media/hls/m1/live.m3u8" },
    { ...replay.clips[1]!, playlist: "/media/hls/m2/live.m3u8", other_match: other },
  ], playback: {
    transitions: { enabled: true, hold_seconds: 0.6, asset: "builtin:league", asset_start_seconds: 0,
      sting_seconds: 2.4, cut_seconds: 0.5, fade_seconds: 0.3 },
    slow_motion: { enabled: false, rate: 0.5, ramp_seconds: 1, before_seconds: 1, after_seconds: 2 },
  } });
  await Promise.resolve();
  const video = get("replay-video");
  assert.equal(streams[0]!.url, "/media/hls/m1/live.m3u8");
  video.paused = false;
  video.currentTime = 11;
  video.emit("timeupdate");
  assert.equal(fire(), 600);  // hold, then the sting
  assert.equal(fire(), 500);  // the cut, under the sting: the other match's stream attaches at the clip
  assert.equal(streams[0]!.destroyed, true);
  assert.equal(streams[1]!.url, "/media/hls/m2/live.m3u8");
  assert.equal(streams[1]!.options.start, 14);
  assert.equal(get("replay-caption").textContent, "2/2 · North FC v South United · 31′ Goal");
  video.currentTime = 24;  // the old stream's last time update means nothing
  video.emit("timeupdate");
  assert.equal(stage.player!.index, 1);
  assert.equal(stage.player!.ended, false);
  await Promise.resolve();
  assert.equal(fire(), 1600);
  video.emit("loadedmetadata");
  assert.equal(video.paused, false);
  video.currentTime = 24;
  video.emit("timeupdate");
  assert.equal(get("replay-caption").textContent, "Replay finished");
  // Replay again goes back to the first match's stream.
  get("replay-again").emit("click");
  assert.equal(streams[1]!.destroyed, true);
  assert.equal(streams[2]!.url, "/media/hls/m1/live.m3u8");
  assert.equal(streams.length, 3);
});
