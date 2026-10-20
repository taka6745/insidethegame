import test from "node:test";
import assert from "node:assert/strict";
import { queueStill, ReplayStage, replayStill } from "../match/replay-view.ts";
import type { StreamOptions } from "../match/media.ts";
import type { Replay } from "../match/types.ts";
import { stub } from "./support.ts";

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
  style: Record<string, string> = {};
  children: Element[] = [];
  parent: Element | null = null;
  listeners: Record<string, ((event?: unknown) => void)[]> = {};
  addEventListener(name: string, fn: (event?: unknown) => void) { (this.listeners[name] ||= []).push(fn); }
  emit(name: string, event?: unknown) { for (const fn of this.listeners[name] || []) fn(event); }
  setAttribute(name: string, value: unknown) { this[name] = value; }
  removeAttribute(name: string) { delete this[name]; }
  replaceChildren(...children: Element[]) { this.children = children; for (const c of children) c.parent = this; }
  get isConnected() { return true; }
  focus() { this.focused = true; }
  async play() { this.paused = false; this.emit("play"); }
  pause() { this.paused = true; this.emit("pause"); }
}
function setup() {
  const nodes = new Map<string, Element>();
  const document = Object.assign(new Element(), {
    getElementById(id: string): Element {
      if (!nodes.has(id)) nodes.set(id, new Element());
      return nodes.get(id)!;
    },
    createElement: () => new Element(),
  });
  const urls: string[] = [], revoked: string[] = [], streams: { url: string; options: StreamOptions; destroyed: boolean }[] = [];
  const stage = new ReplayStage(stub<Document>(document), {
    origin: "http://localhost",
    urls: { createObjectURL: () => { urls.push(`blob:${urls.length}`); return urls.at(-1)!; },
      revokeObjectURL: (url: string) => { revoked.push(url); } },
    attach: async (_video, url, options) => {
      const stream = { url, options, destroyed: false };
      streams.push(stream);
      return { destroy: () => { stream.destroyed = true; } };
    },
  });
  const get = (id: string) => document.getElementById(id);
  return { stage, document, get, urls, revoked, streams };
}
const replay: Replay = {
  page: 0, page_size: 12, total_items: 2, seconds: 20, playlist: "#EXTM3U\n/media/hls/00001.ts\n",
  clips: [
    { start: 100, end: 110, captions: ["23′ Palmer header saved"], playlist_start: 1, playlist_end: 11, marks: [106] },
    { start: 200, end: 210, captions: ["31′ Goal"], playlist_start: 14, playlist_end: 24 },
  ],
};

test("Play moves the replay to the stage, live becomes the corner picture, Back to live restores it", async () => {
  const { stage, get, urls, revoked, streams } = setup();
  const opener = new Element();
  stage.open(replay, stub<HTMLElement>(opener));
  await Promise.resolve();
  assert.equal(get("match-stage").dataset.mode, "replay");
  assert.equal(get("replay-video").hidden, false);
  assert.equal(get("pip-return").hidden, false);
  assert.equal(get("replay-video").muted, true);
  assert.equal(streams[0]!.url, "blob:0");
  assert.deepEqual(streams[0]!.options.start, 1);
  assert.equal(get("replay-caption").textContent, "1/2 · 23′ Palmer header saved");
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
  assert.deepEqual(revoked, urls);
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
  const { stage, get, urls } = setup();
  stage.open({ ...replay, playlist: null });
  assert.equal(stage.isOpen, false);
  assert.equal(get("match-stage").dataset.mode, undefined);
  assert.deepEqual(urls, []);
});


test("chat stills draw the middle of the first clip and release the player and Blob URL", async () => {
  const drawn: unknown[] = [], urls: string[] = [], revoked: string[] = [];
  let video: Element | null = null, destroyed = false;
  const canvas = {
    width: 0, height: 0,
    ownerDocument: { createElement: () => (video = Object.assign(new Element(), { videoWidth: 1280, videoHeight: 720 })) },
    getContext: () => ({ drawImage: (...args: unknown[]) => drawn.push(args) }),
  };
  const done = replayStill(replay, stub<HTMLCanvasElement>(canvas), {
    origin: "http://localhost",
    urls: { createObjectURL: () => { urls.push("blob:still"); return "blob:still"; },
      revokeObjectURL: (url: string) => { revoked.push(url); } },
    attach: async (_video, _url, options) => {
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
  assert.deepEqual(revoked, urls);
});


test("a published-stream replay seeks match video times without a Blob playlist", async () => {
  const { stage, urls, streams } = setup();
  stage.open({ ...replay, playlist: "/media/hls/live.m3u8",
    clips: replay.clips.map((clip) => ({ ...clip, playlist_start: clip.start, playlist_end: clip.end })) });
  await Promise.resolve();
  assert.deepEqual(urls, []);
  assert.equal(streams[0]!.url, "/media/hls/live.m3u8");
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
