import test from "node:test";
import assert from "node:assert/strict";
import { HeldUpdates } from "../match/hold.ts";
import { absolutePlaylist, attachStream, liveSource, playbackEngine } from "../match/media.ts";
import type { HlsConstructor } from "../match/media.ts";
import {
  derivedText, duration, hasMore, pageCount, playableClips, reelProgress, reelTimeline, ReplayPlayer,
} from "../match/replay.ts";
import type { Replay } from "../match/types.ts";
import { stub } from "./support.ts";

const clip = (start: number, end: number, caption: string) =>
  ({ start: start + 100, end: end + 100, captions: [caption], playlist_start: start, playlist_end: end });
const replay = (over: Partial<Replay> = {}): Replay => ({
  page: 0, page_size: 12, total_items: 2, seconds: 18, playlist: "#EXTM3U\n",
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

test("media mode selects live HLS only when the producer publishes it", () => {
  assert.deepEqual(liveSource({ live: true, url: "/media/hls/live.m3u8" }), { kind: "hls", url: "/media/hls/live.m3u8" });
  assert.deepEqual(liveSource({ live: true }), { kind: "hls", url: "/media/hls/live.m3u8" });
  assert.deepEqual(liveSource({ aligned: true, url: "/media/simulator.mp4" }), { kind: "mp4", url: "/media/simulator.mp4" });
  assert.deepEqual(liveSource(undefined), { kind: "mp4", url: "/media/simulator.mp4" });
  assert.equal(playbackEngine(true, "maybe"), "hls.js");
  assert.equal(playbackEngine(false, "maybe"), "native");
  assert.equal(playbackEngine(false, ""), "none");
});

test("replay playlists get absolute segment URLs so a Blob URL can play them", () => {
  const text = "#EXTM3U\n#EXTINF:2.000,\n/media/hls/00012.ts\n#EXT-X-ENDLIST\n";
  assert.equal(absolutePlaylist(text, "http://localhost:18020"),
    "#EXTM3U\n#EXTINF:2.000,\nhttp://localhost:18020/media/hls/00012.ts\n#EXT-X-ENDLIST\n");
});

function fakeHls(supported = true) {
  const made: { config: Record<string, unknown>; source?: string; media?: unknown; destroyed: number;
    recovered: number; restarted: number;
    handlers: Record<string, (event: unknown, data: { fatal: boolean; type?: string }) => void> }[] = [];
  class Player {
    static isSupported = () => supported;
    static Events = { ERROR: "hlsError", FRAG_BUFFERED: "hlsFragBuffered" };
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
  src: "", currentTime: 0, canPlayType: () => native, removeAttribute(name: string) { if (name === "src") this.src = ""; }, load() {},
});

test("live HLS uses hls.js without workers and stays three segments from the edge", async () => {
  const hls = fakeHls(), video = videoDouble();
  let errors = 0;
  const stream = await attachStream(stub<HTMLVideoElement>(video), "/media/hls/live.m3u8",
    { live: true, loader: hls.loader, onError: () => errors++ });
  const [player] = hls.made;
  assert.deepEqual(player!.config, { enableWorker: false, lowLatencyMode: false, liveSyncDurationCount: 3,
    liveMaxLatencyDurationCount: 10, maxLiveSyncPlaybackRate: 1.1, backBufferLength: 30 });
  assert.equal(player!.source, "/media/hls/live.m3u8");
  assert.equal(player!.media, video);
  player!.handlers.hlsError!(null, { fatal: false });
  assert.equal(errors, 0);
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

test("replay VOD starts at its first clip; native HLS is the fallback, otherwise unavailable", async () => {
  const hls = fakeHls();
  await attachStream(stub<HTMLVideoElement>(videoDouble()), "blob:x", { live: false, start: 4.5, loader: hls.loader });
  assert.deepEqual(hls.made[0]!.config, { enableWorker: false, lowLatencyMode: false, startPosition: 4.5,
    maxBufferLength: 12, maxMaxBufferLength: 30, backBufferLength: 10 });
  const native = videoDouble("maybe");
  const stream = await attachStream(stub<HTMLVideoElement>(native), "/media/hls/live.m3u8",
    { live: true, loader: fakeHls(false).loader });
  assert.equal(native.src, "/media/hls/live.m3u8");
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
  });
  assert.equal((await api.replayPage("tok en", 7, 1)).page, 1);
  assert.equal(calls[0]![0], "/viewer-api/tok%20en/turns/7/replay/1");
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
