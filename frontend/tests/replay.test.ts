import test from "node:test";
import assert from "node:assert/strict";
import { HeldUpdates } from "../match/hold.ts";
import { attachStream, liveCatchUp, liveSource, playbackEngine } from "../match/media.ts";
import type { HlsConstructor } from "../match/media.ts";
import {
  derivedText, duration, hasMore, pageCount, playableClips, reelProgress, reelTimeline, ReplayPlayer, slowRate,
} from "../match/replay.ts";
import type { Playback, Replay } from "../match/types.ts";
import { stub } from "./support.ts";

const clip = (start: number, end: number, caption: string) =>
  ({ start: start + 100, end: end + 100, captions: [caption], playlist_start: start, playlist_end: end });
const replay = (over: Partial<Replay> = {}): Replay => ({
  page: 0, page_size: 12, total_items: 2, seconds: 18, playlist: "/media/hls/m1/live.m3u8",
  clips: [clip(1, 9, "23′ Palmer header saved"), clip(12, 22, "31′ Goal")], ...over,
});

test("held live states wait for the live playhead and release the newest reached state", () => {
  const held = new HeldUpdates<string>();
  held.push("a", 10, 0);
  held.push("b", 12, 100);
  held.push("c", 20, 200);
  assert.equal(held.release(9.5, 300), undefined);
  assert.equal(held.release(12, 400), "b");
  assert.equal(held.size, 1);
  assert.equal(held.release(19.9, 500), undefined);
  assert.equal(held.release(25, 600), "c");
  assert.equal(held.size, 0);
});

test("held states release immediately without a live picture, without producer time, or after 15 s", () => {
  const held = new HeldUpdates<string>();
  held.push("no-picture", 50, 0);
  assert.equal(held.release(null, 0), "no-picture");
  held.push("untimed", null, 0);
  assert.equal(held.release(1, 0), "untimed");
  held.push("stalled", 50, 0);
  assert.equal(held.release(1, 14999), undefined);
  assert.equal(held.release(1, 15000), "stalled");
  const bounded = new HeldUpdates<number>(15000, 3);
  for (let i = 0; i < 10; i++) bounded.push(i, 100 + i, 0);
  assert.equal(bounded.size, 3);
  assert.equal(bounded.release(200, 1), 9);
});

test("a full hold queue keeps releasing at most maxHold behind arrival instead of freezing", () => {
  // 3.3 states/s, each 17 s ahead of the picture: the 30-state cap is under 15 s of data.
  const held = new HeldUpdates<number>();
  let last = -1, worst = 0;
  for (let ms = 0; ms <= 120000; ms += 300) {
    const t = ms / 1000;
    held.push(ms, t + 17, ms);
    const ready = held.release(t, ms);
    if (ready !== undefined) last = ready;
    if (ms >= 15000) worst = Math.max(worst, ms - last);
  }
  assert.ok(held.size <= 30);
  assert.ok(worst <= 15000, `released state lagged ${worst} ms`);
});

test("media mode selects live HLS only when the producer publishes it", () => {
  assert.deepEqual(liveSource({ url: "/media/hls/m1/live.m3u8" }), { kind: "hls", url: "/media/hls/m1/live.m3u8" });
  // No fallback playlist: a match without its own published stream has no footage.
  assert.equal(liveSource({ seconds: 3 }), null);
  assert.deepEqual(liveSource({ url: "/media/hls/run-1/live.m3u8" }), { kind: "hls", url: "/media/hls/run-1/live.m3u8" });
  assert.equal(liveSource({ url: "/media/simulator.mp4" }), null);  // No full-match fallback.
  assert.equal(liveSource(undefined), null);
  assert.deepEqual(liveSource({ url: "/media/hls/m1/live.m3u8", seconds: 3 }), { kind: "hls", url: "/media/hls/m1/live.m3u8" });
  assert.equal(liveSource({ url: null, seconds: 3 }), null);
  assert.equal(playbackEngine(true, "maybe"), "hls.js");
  assert.equal(playbackEngine(false, "maybe"), "native");
  assert.equal(playbackEngine(false, ""), "none");
});

function fakeHls(supported = true) {
  const made: { config: Record<string, unknown>; source?: string; media?: unknown; destroyed: number;
    recovered: number; restarted: number;
    handlers: Record<string, (event: unknown, data: { fatal: boolean; type?: string }) => void> }[] = [];
  class Player {
    static isSupported = () => supported;
    static Events = { ERROR: "hlsError", FRAG_BUFFERED: "hlsFragBuffered", MANIFEST_PARSED: "hlsManifestParsed" };
    static ErrorTypes = { MEDIA_ERROR: "mediaError", NETWORK_ERROR: "networkError" };
    state: (typeof made)[number];
    constructor(config: Record<string, unknown>) {
      this.state = { config, destroyed: 0, recovered: 0, restarted: 0, handlers: {} };
      made.push(this.state);
    }
    on(name: string, fn: (event: unknown, data: { fatal: boolean; type?: string }) => void) { this.state.handlers[name] = fn; }
    recoverMediaError() { this.state.recovered++; }
    startLoad() { this.state.restarted++; }
    loadSource(url: string) { this.state.source = url; }
    attachMedia(media: unknown) { this.state.media = media; }
    destroy() { this.state.destroyed++; }
  }
  return { made, loader: async () => stub<HlsConstructor>(Player) };
}
const videoDouble = (native = "") => ({
  src: "", currentTime: 0, playbackRate: 1, canPlayType: () => native, removeAttribute(name: string) { if (name === "src") this.src = ""; }, load() {},
});

test("live HLS uses hls.js without workers and stays three segments from the edge", async () => {
  const hls = fakeHls(), video = videoDouble();
  let errors = 0;
  const stream = await attachStream(stub<HTMLVideoElement>(video), "/media/hls/m1/live.m3u8",
    { live: true, loader: hls.loader, onError: () => errors++ });
  const [player] = hls.made;
  assert.deepEqual(player!.config, { enableWorker: false, lowLatencyMode: false, liveSyncDurationCount: 3,
    liveMaxLatencyDurationCount: 6, liveSyncOnStallIncrease: 0, backBufferLength: 30 });
  assert.equal(player!.source, "/media/hls/m1/live.m3u8");
  assert.equal(player!.media, video);
  player!.handlers.hlsError!(null, { fatal: false });
  assert.equal(errors, 0);
  player!.handlers.hlsManifestParsed!(null, { fatal: false });
  // Fatal media and network errors recover in place, keeping the picture, before giving up.
  player!.handlers.hlsError!(null, { fatal: true, type: "mediaError" });
  player!.handlers.hlsError!(null, { fatal: true, type: "networkError" });
  player!.handlers.hlsFragBuffered!(null, { fatal: false });  // Progress resets the budget.
  for (let i = 0; i < 3; i++) player!.handlers.hlsError!(null, { fatal: true, type: "networkError" });
  assert.deepEqual([player!.recovered, player!.restarted, errors, player!.destroyed], [1, 4, 0, 0]);
  player!.handlers.hlsError!(null, { fatal: true, type: "networkError" });
  stream.destroy();
  assert.equal(errors, 1);
  assert.equal(player!.destroyed, 1);
});

test("a live playlist that is not published yet gives up so the viewer attaches again", async () => {
  const hls = fakeHls();
  let errors = 0;
  await attachStream(stub<HTMLVideoElement>(videoDouble()), "/media/hls/m1/live.m3u8",
    { live: true, loader: hls.loader, onError: () => errors++ });
  hls.made[0]!.handlers.hlsError!(null, { fatal: true, type: "networkError" });  // the playlist's 404
  assert.deepEqual([hls.made[0]!.restarted, hls.made[0]!.destroyed, errors], [0, 1, 1]);
});

test("replay VOD starts at its first clip; native HLS is the fallback, otherwise unavailable", async () => {
  const hls = fakeHls();
  await attachStream(stub<HTMLVideoElement>(videoDouble()), "/media/hls/m1/live.m3u8", { live: false, start: 4.5, loader: hls.loader });
  assert.deepEqual(hls.made[0]!.config, { enableWorker: false, lowLatencyMode: false, startPosition: 4.5,
    maxBufferLength: 12, maxMaxBufferLength: 30, backBufferLength: 10 });
  const native = videoDouble("maybe");
  const stream = await attachStream(stub<HTMLVideoElement>(native), "/media/hls/m1/live.m3u8",
    { live: true, loader: fakeHls(false).loader });
  assert.equal(native.src, "/media/hls/m1/live.m3u8");
  stream.destroy();
  assert.equal(native.src, "");
  let errors = 0;
  await attachStream(stub<HTMLVideoElement>(videoDouble()), "/x.m3u8",
    { live: true, loader: async () => null, onError: () => errors++ });
  assert.equal(errors, 1);
});

test("replay player auto-advances at each out point and stops after the last clip", () => {
  const player = new ReplayPlayer(playableClips(replay()));
  assert.equal(player.caption(), "1/2 · 23′ Palmer header saved");
  assert.deepEqual(player.time(5), {});
  assert.deepEqual(player.time(9), { seek: 12 });
  assert.equal(player.index, 1);
  assert.equal(player.caption(), "2/2 · 31′ Goal");
  assert.deepEqual(player.time(10), {}); // stale time while seeking does not skip ahead
  assert.deepEqual(player.time(22), { ended: true });
  assert.equal(player.ended, true);
  assert.deepEqual(player.time(23), {});
  assert.deepEqual(player.go(0), { seek: 1 });
  assert.equal(player.ended, false);
});

test("replay navigation clamps previous and finishes on next from the last clip", () => {
  const player = new ReplayPlayer(playableClips(replay()));
  assert.deepEqual(player.previous(), { seek: 1 });
  assert.deepEqual(player.next(), { seek: 12 });
  assert.deepEqual(player.next(), { ended: true });
  assert.deepEqual(new ReplayPlayer([]).go(0), { ended: true });
});

test("paging, length and derived definitions are derived from the replay contract", () => {
  assert.equal(hasMore(replay({ total_items: 12 })), false);
  assert.equal(hasMore(replay({ total_items: 13 })), true);
  assert.equal(hasMore(replay({ page: 1, total_items: 24 })), false);
  assert.equal(pageCount(replay({ total_items: 25 })), 3);
  // Server page counts win: long clips can fill a page before 12 items.
  assert.equal(pageCount(replay({ total_items: 12, page_count: 3 })), 3);
  assert.equal(hasMore(replay({ page: 1, total_items: 12, page_count: 3 })), true);
  assert.equal(duration(102.4), "01:42");
  assert.deepEqual(playableClips(replay({ playlist: null })), []);
  assert.deepEqual(playableClips(replay({ clips: [{ start: 1, end: 2 }] })), []);
  assert.equal(derivedText({ first: { event_types: ["pass"], outcome: "failed" },
    then: { event_types: ["touch"] }, within_seconds: 3, then_team: "opponent" }),
  "failed pass, then opponent touch within 3 s");
  assert.equal(derivedText(null), "");
});

test("next replay page is a GET on the saved turn", async () => {
  const { MatchApi } = await import("../match/api.ts");
  const calls: [string, RequestInit][] = [];
  const api = new MatchApi(async (url, init) => {
    calls.push([url, init]);
    return { ok: true, status: 200, json: async () => replay({ page: 1 }) };
  }, "/viewer-api", "m1");
  assert.equal((await api.replayPage("tok en", 7, 1)).page, 1);
  assert.equal(calls[0]![0], "/viewer-api/matches/m1/sessions/tok%20en/turns/7/replay/1");
  assert.equal(calls[0]![1].method, "GET");
});

test("the reel bar spans every clip: marks and joins by cumulative playback", () => {
  const clips = [clip(1, 11, "a"), clip(14, 24, "b")].map((c, i) => ({ ...c, marks: [c.start + (i ? 9 : 5)] }));
  const timeline = reelTimeline(clips);
  assert.deepEqual([timeline.joins, timeline.marks], [[50], [25, 95]]);
  const player = new ReplayPlayer(clips);
  assert.equal(reelProgress(player, 6, timeline), 25);
  player.go(1);
  assert.equal(reelProgress(player, 19, timeline), 75);
  player.finish();
  assert.equal(reelProgress(player, 0, timeline), 100);
});

test("after a stall the live picture returns to the target latency without seek loops", () => {
  const jobs: (() => void)[] = [];
  const timers = { setTimeout: (fn: () => void) => { jobs.push(fn); return jobs.length; }, clearTimeout() {} };
  const tick = () => jobs.shift()!();
  const hls = { liveSyncPosition: 100 as number | null };
  const video = { currentTime: 100, paused: false, seeking: false, readyState: 4, playbackRate: 1 };
  const stop = liveCatchUp(video, hls, timers);
  tick();
  assert.equal(video.playbackRate, 1);  // On target: nothing changes.
  // Small drift: catch up slightly faster, back to normal speed once close.
  video.currentTime = 97;
  tick();
  assert.equal(video.playbackRate, 1.1);
  video.currentTime = 99.8;
  tick();
  assert.equal(video.playbackRate, 1);
  // A stall leaves the picture 15 s behind (the 31' report): one seek after three sustained seconds.
  hls.liveSyncPosition = 200;
  video.currentTime = 185;
  tick(); tick();
  assert.equal(video.currentTime, 185);
  tick();
  assert.equal(video.currentTime, 200);
  // Still behind straight after (e.g. the seek landed short): no repeat seek during the cooldown.
  video.currentTime = 190;
  for (let i = 0; i < 9; i++) tick();
  assert.equal(video.currentTime, 190);
  assert.equal(video.playbackRate, 1.1);
  tick();
  assert.equal(video.currentTime, 200);
  // Paused, seeking or buffering pictures are left alone; stopping restores normal speed.
  video.currentTime = 150; video.paused = true;
  for (let i = 0; i < 5; i++) tick();
  assert.equal(video.currentTime, 150);
  video.paused = false; video.playbackRate = 1.1;
  stop();
  assert.equal(video.playbackRate, 1);
});

const playback = (over: { transitions?: Partial<Playback["transitions"]>; slow?: Partial<Playback["slow_motion"]> } = {}): Playback => ({
  transitions: { enabled: true, hold_seconds: 0.6, asset: "/assets/league/sting/replay-sting.mp4", asset_start_seconds: 0.15,
    sting_seconds: 2.4, cut_seconds: 0.5, fade_seconds: 0.3, ...over.transitions },
  slow_motion: { enabled: true, rate: 0.5, ramp_seconds: 1, before_seconds: 1, after_seconds: 2, ...over.slow },
});
const three = () => playableClips(replay({ clips: [clip(1, 9, "a"), clip(12, 22, "b"), clip(30, 40, "c")] }));

test("between clips the reel holds, stings, cuts under the sting and plays the next clip as it fades", () => {
  const player = new ReplayPlayer(three(), playback());
  assert.deepEqual(player.time(9), { pause: true, wait: 0.6 });  // hold the last frame
  assert.equal(player.phase, "holding");
  assert.deepEqual(player.time(9.2), {});  // stale time updates change nothing while held
  assert.deepEqual(player.advance(), { sting: "in", wait: 0.5 });
  assert.equal(player.index, 0);
  assert.deepEqual(player.advance(), { seek: 12, pause: true, wait: 1.6 });  // 2.4 - 0.3 fade - 0.5 cut
  assert.equal(player.index, 1);
  assert.equal(player.caption(), "2/3 · b");
  assert.deepEqual(player.advance(), { play: true, sting: "out" });
  assert.equal(player.phase, "playing");
  assert.deepEqual(player.advance(), {});  // a late timer is harmless
  assert.deepEqual(player.time(22), { pause: true, wait: 0.6 });
  player.advance(); player.advance(); player.advance();
  assert.equal(player.index, 2);
  assert.deepEqual(player.time(40), { ended: true });  // the last clip ends without a sting
});

test("skip and navigation cancel a hold or sting; reduced motion and disabled transitions just cut", () => {
  const held = new ReplayPlayer(three(), playback());
  held.time(9);
  assert.deepEqual(held.skip(), { seek: 12 });  // play/pause while held jumps on
  assert.equal(held.phase, "playing");
  const stinging = new ReplayPlayer(three(), playback());
  stinging.time(9); stinging.advance();
  assert.deepEqual(stinging.go(2), { seek: 30, play: true, sting: "out" });  // seeking during the sting
  const cued = new ReplayPlayer(three(), playback());
  cued.time(9); cued.advance(); cued.advance();
  assert.deepEqual(cued.skip(), { seek: 12, play: true, sting: "out" });  // the cued clip starts now
  assert.deepEqual(cued.previous(), { seek: 1 });
  const reduced = new ReplayPlayer(three(), playback(), { reducedMotion: true });
  assert.deepEqual(reduced.time(9), { pause: true, wait: 0.6 });  // a pause is not motion
  assert.deepEqual(reduced.advance(), { seek: 12 });
  const off = new ReplayPlayer(three(), playback({ transitions: { enabled: false } }));
  assert.deepEqual(off.time(9), { seek: 12 });
  assert.deepEqual(new ReplayPlayer(three()).time(9), { seek: 12 });  // older replays carry no playback
});

test("slow motion eases into the marked event, holds through it and eases out", () => {
  const marked = { start: 100, end: 110, playlist_start: 1, playlist_end: 11, marks: [106] };  // event at 7 s
  const slow = playback().slow_motion;
  assert.equal(slowRate(marked, 2, slow), 1);
  assert.equal(slowRate(marked, 5.5, slow), 0.75);  // halfway down the 1 s ramp before 6 s
  assert.equal(slowRate(marked, 6, slow), 0.5);
  assert.equal(slowRate(marked, 8.5, slow), 0.5);
  assert.equal(slowRate(marked, 9.5, slow), 0.75);
  assert.equal(slowRate(marked, 10.5, slow), 1);
  assert.equal(slowRate(marked, 7, { ...slow, enabled: false }), 1);
  assert.equal(slowRate({ ...marked, marks: [] }, 7, slow), 1);
  const player = new ReplayPlayer(playableClips(replay({ clips: [marked] })), playback(), { reducedMotion: true });
  assert.equal(player.rate(7), 1);
  assert.equal(new ReplayPlayer(playableClips(replay({ clips: [marked] })), playback()).rate(7), 0.5);
});
