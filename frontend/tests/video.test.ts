import test from "node:test";
import assert from "node:assert/strict";
import { attachDemoVideo } from "../match/video.ts";
import type { DemoVideo } from "../match/video.ts";
import { stub } from "./support.ts";

interface ElementDouble {
  [attribute: string]: unknown;
  hidden: boolean;
  listeners: Record<string, (event?: unknown) => unknown>;
  paused?: boolean;
  src?: string;
  muted?: boolean;
  loop?: boolean;
  autoplay?: boolean;
  tabIndex?: number;
  currentTime?: number;
  play?: () => Promise<void>;
  pause?: () => void;
  setAttribute(name: string, value: unknown): void;
  addEventListener(name: string, fn: (event?: unknown) => unknown): void;
}
function setup(options?: { reducedMotion?: boolean }) {
  const elements: Record<string, ElementDouble> = Object.fromEntries(
    ["match-video", "video-empty"].map(id => [id, {
      hidden: true, listeners: {},
      setAttribute(name: string, value: unknown) { this[name] = value; },
      addEventListener(name: string, fn: () => unknown) { this.listeners[name] = fn; },
      removeAttribute(name: string) { if (name === "src") this.src = ""; },
    } as ElementDouble]),
  );
  const video = elements["match-video"]!;
  video.paused = true;
  video.play = async () => { video.paused = false; };
  video.pause = () => { video.paused = true; video.listeners.pause!(); };
  const controller = attachDemoVideo(stub<Document>({ getElementById: (id: string) => elements[id] }), options);
  return { video, empty: elements["video-empty"]!, controller };
}
const sync = (controller: DemoVideo, match: object) => controller.sync(match);

test("without a live stream nothing is requested and the empty state shows", async () => {
  const elements = setup(), video = elements.video;
  assert.equal(video.src ?? "", "");  // Nothing is requested before the server describes the media.
  sync(elements.controller, { id: "m1", status: "scheduled" });
  assert.equal(video.src ?? "", "");  // Never a full-match MP4 fallback.
  assert.equal(video.muted, true);
  assert.equal(video.hidden, true);
  assert.equal(elements.empty.hidden, false);
});

test("reduced motion starts paused and the footage toggle can play and pause without seeking", async () => {
  const elements = setup({ reducedMotion: true }), video = elements.video;
  video.listeners.loadeddata!();
  assert.equal(video.autoplay, false);
  assert.equal(video.paused, true);
  assert.equal(video.tabIndex, 0);
  await video.listeners.click!();
  assert.equal(video.paused, false);
  assert.equal(video["aria-label"], "Pause match footage");
  await video.listeners.click!();
  assert.equal(video.paused, true);
  assert.equal(video["aria-label"], "Play match footage");
});

test("blocked play keeps a deliberate retry available", async () => {
  const elements = setup({ reducedMotion: true }), video = elements.video;
  video.play = async () => { throw new Error("Autoplay blocked"); };
  video.listeners.loadeddata!();
  await video.listeners.click!();
  assert.equal(video.tabIndex, 0);
  assert.equal(video["aria-label"], "Play match footage");
});

test("keyboard activation toggles footage and prevents page scrolling", async () => {
  const elements = setup({ reducedMotion: true }), video = elements.video;
  let prevented = false;
  video.listeners.keydown!({ key: " ", preventDefault() { prevented = true; } });
  await Promise.resolve();
  assert.equal(prevented, true);
  assert.equal(video.paused, false);
});


test("media without live HLS never loads footage, even at full time", async () => {
  const elements = setup({ reducedMotion: true }), video = elements.video;
  for (const status of ["scheduled", "live", "finished"]) {
    sync(elements.controller, { id: "m1", status, media: { seconds: 720, url: null } });
    assert.equal(video.src ?? "", "");
    assert.equal(video.hidden, true);
    assert.equal(elements.empty.hidden, false);
  }
  assert.equal(elements.controller.playhead(), null);
});

test("live HLS attaches once, plays at the edge and reports its playhead for held data", async () => {
  const elements = setup({ reducedMotion: true }), video = elements.video;
  const attached: string[] = [];
  Object.assign(video, {
    readyState: 0, canPlayType: () => "", load() {},
    removeAttribute(name: string) { if (name === "src") video.src = ""; },
  });
  const loader = async () => {
    attached.push("load");
    return null;
  };
  const live = attachDemoVideo(stub<Document>({ getElementById: (id: string) =>
    id === "match-video" ? video : elements.empty }), { reducedMotion: true, loader });
  const match = { id: "m1", status: "live", media: { seconds: 30, url: "/media/hls/m1/live.m3u8" } };
  live.sync(match);
  live.sync({ ...match, media: { ...match.media, seconds: 31 } });
  await new Promise((done) => setTimeout(done));
  assert.equal(video.src, "");
  assert.deepEqual(attached, ["load"]); // no hls.js and no native HLS: one attempt, then unavailable
  assert.equal(video.hidden, true);
  assert.equal(elements.empty.hidden, false);
  assert.equal(live.playhead(), null);
  video.listeners.loadeddata!();
  Object.assign(video, { readyState: 4, paused: false, currentTime: 24 });
  assert.equal(live.playhead(), 24);
  Object.assign(video, { readyState: 1, currentTime: 30 }); // seeking to the edge: still holds
  assert.equal(live.playhead(), 30);
  live.disconnect();
  assert.equal(video.paused, false); // live HLS keeps its own edge while the socket reconnects
  assert.equal(video.loop, false);
});

test("after full time live HLS opens paused at the final picture, not at kick-off", async () => {
  const elements = setup({ reducedMotion: true }), video = elements.video;
  const configs: Record<string, unknown>[] = [];
  Object.assign(video, { canPlayType: () => "", load() {}, removeAttribute() {} });
  class Player {
    static isSupported = () => true;
    static Events = { ERROR: "hlsError", FRAG_BUFFERED: "hlsFragBuffered" };
    static ErrorTypes = {};
    constructor(config: Record<string, unknown>) { configs.push(config); }
    on() {}
    loadSource() {}
    attachMedia() {}
    destroy() {}
  }
  const live = attachDemoVideo(stub<Document>({ getElementById: (id: string) =>
    id === "match-video" ? video : elements.empty }), { reducedMotion: true, loader: async () => stub(Player) });
  live.sync({ id: "m1", status: "finished", media: { seconds: 5515, url: "/media/hls/m1/live.m3u8" } });
  await new Promise((done) => setTimeout(done));
  assert.equal(configs[0]!.startPosition, 5514.5);
  assert.equal(video.paused, true);
  assert.equal(live.playhead(), null); // A still picture releases held insights.
});
