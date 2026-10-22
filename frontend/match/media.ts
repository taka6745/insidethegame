import type Hls from "hls.js";
import type { MatchMedia, Timers } from "./types.ts";

export type HlsConstructor = typeof Hls;
export type HlsLoader = () => Promise<HlsConstructor | null>;
export type Engine = "hls.js" | "native" | "none";
export interface Stream {
  destroy(): void;
}
export interface StreamOptions {
  live: boolean;
  /** Playlist time to start from (replay clips). */
  start?: number;
  onError?: () => void;
  loader?: HlsLoader;
  /** A one-frame still: buffer as little as possible. */
  capture?: boolean;
  timers?: Timers;
}
const HLS_TYPE = "application/vnd.apple.mpegurl";

/** The match's own live HLS when the snapshot names one; otherwise no footage, never a full-match file. */
export function liveSource(media?: MatchMedia | null): { kind: "hls"; url: string } | null {
  const url = media?.url;
  return url && /\.m3u8(?:\?|$)/.test(url) ? { kind: "hls", url } : null;
}

/** hls.js where Media Source is available; native HLS (Safari) only as the fallback. */
export function playbackEngine(hlsSupported: boolean, nativeSupport: string): Engine {
  if (hlsSupported) return "hls.js";
  return nativeSupport ? "native" : "none";
}

/** The vendored ES module ships from this origin beside the app (strict CSP, no workers). */
export const loadHls: HlsLoader = async () => {
  try {
    const url = new URL("./vendor/hls.js", import.meta.url).href;
    return ((await import(url)) as { default: HlsConstructor }).default;
  } catch {
    return null;
  }
};

/** Live chases the edge with bounded drift; replays and stills keep bounded buffers. Replays
 * never set a max latency: any finite value would jump them to the live edge. */
export function streamConfig(live: boolean, start?: number, capture = false) {
  const base = { enableWorker: false, lowLatencyMode: false };
  // A finished or paused match opens where the server says play is, not at 00:00.
  // A fixed target: hls.js otherwise adds a second per stall and never gives it back. Drift beyond
  // it is recovered by liveCatchUp (hls.js only adjusts the rate in low-latency mode).
  if (live) return { ...base, liveSyncDurationCount: 3, liveMaxLatencyDurationCount: 6,
    liveSyncOnStallIncrease: 0, backBufferLength: 30, ...(start === undefined ? {} : { startPosition: start }) };
  return capture
    ? { ...base, startPosition: start ?? -1, maxBufferLength: 2, maxMaxBufferLength: 4, backBufferLength: 0 }
    : { ...base, startPosition: start ?? -1, maxBufferLength: 12, maxMaxBufferLength: 30, backBufferLength: 10 };
}

export type CatchUpVideo = Pick<HTMLVideoElement, "currentTime" | "paused" | "seeking" | "readyState" | "playbackRate">;
export const CATCH_UP = { tick: 1000, rateAbove: 1.5, settle: 0.5, rate: 1.1, seekAbove: 6, sustain: 3, cooldown: 10 };

/** Returns a playing live picture to hls.js's target after a stall: slightly faster playback for
 * small drift; one seek to the sync position when far behind for `sustain` ticks, then a cooldown
 * so it never loops. Returns a stop function. */
export function liveCatchUp(video: CatchUpVideo, hls: { readonly liveSyncPosition: number | null },
  timers: Timers = globalThis, options: Partial<typeof CATCH_UP> = {}): () => void {
  const { tick, rateAbove, settle, rate, seekAbove, sustain, cooldown } = { ...CATCH_UP, ...options };
  let behind = 0, ticks = 0, quietUntil = 0, timer: unknown = null, stopped = false;
  const normal = () => { if (video.playbackRate !== 1) video.playbackRate = 1; };
  const check = () => {
    ticks++;
    const sync = hls.liveSyncPosition;
    if (video.paused || video.seeking || video.readyState < 3 || sync === null || !Number.isFinite(sync)) {
      behind = 0;
      normal();
      return;
    }
    const drift = sync - video.currentTime;
    behind = drift > seekAbove ? behind + 1 : 0;
    if (behind >= sustain && ticks >= quietUntil) {
      behind = 0;
      quietUntil = ticks + cooldown;
      normal();
      video.currentTime = sync;
    } else if (drift > rateAbove) {
      if (video.playbackRate !== rate) video.playbackRate = rate;
    } else if (drift < settle) normal();
  };
  const schedule = () => {
    timer = timers.setTimeout(() => {
      if (stopped) return;
      check();
      schedule();
    }, tick);
    (timer as { unref?: () => void } | null)?.unref?.();
  };
  schedule();
  return () => {
    stopped = true;
    timers.clearTimeout(timer);
    normal();
  };
}

export async function attachStream(
  video: HTMLVideoElement,
  url: string,
  { live, start, onError, loader = loadHls, capture = false, timers }: StreamOptions,
): Promise<Stream> {
  const Player = await loader();
  const engine = playbackEngine(Boolean(Player?.isSupported()), video.canPlayType(HLS_TYPE));
  if (engine === "hls.js") {
    const hls = new Player!(streamConfig(live, start, capture));
    let active = true, recoveries = 0, parsed = false;
    const stopCatchUp = live ? liveCatchUp(video, hls, timers) : () => {};
    const destroy = () => {
      stopCatchUp();
      if (active) hls.destroy();
      active = false;
    };
    hls.on(Player!.Events.FRAG_BUFFERED, () => { recoveries = 0; });
    hls.on(Player!.Events.MANIFEST_PARSED, () => { parsed = true; });
    hls.on(Player!.Events.ERROR, (_event, data) => {
      if (!data.fatal) return;
      // A single-level stream escalates stalls and missing segments to fatal; recover in place
      // (keeping the last frame) before giving up, which would blank the picture. Without a
      // playlist yet (opened before its first segment played) startLoad does nothing: give up so
      // the caller attaches again.
      if (parsed && recoveries++ < 3) {
        if (data.type === Player!.ErrorTypes.MEDIA_ERROR) return hls.recoverMediaError();
        if (data.type === Player!.ErrorTypes.NETWORK_ERROR) return hls.startLoad(video.currentTime);
      }
      destroy();
      onError?.();
    });
    hls.loadSource(url);
    hls.attachMedia(video);
    return { destroy };
  }
  const clear = () => {
    video.removeAttribute("src");
    video.load();
  };
  if (engine === "native") {
    video.src = url;
    return { destroy: clear };
  }
  onError?.();
  return { destroy() {} };
}

/** One still at `seconds` of a playlist for a chat card; the player is released once it draws. */
export function captureFrame(
  canvas: HTMLCanvasElement,
  url: string,
  seconds: number,
  attach: typeof attachStream = attachStream,
  timeoutMs = 15000,
): Promise<boolean> {
  const video = canvas.ownerDocument.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  return new Promise((resolve) => {
    let stream: Stream | null = null, settled = false;
    const finish = (drawn: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      stream?.destroy();
      resolve(drawn);
    };
    const timer = setTimeout(() => finish(false), timeoutMs);
    video.addEventListener("loadeddata", () => { video.currentTime = seconds; }, { once: true });
    video.addEventListener("seeked", () => {
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 360;
      canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
      finish(true);
    }, { once: true });
    attach(video, url, { live: false, start: seconds, capture: true, onError: () => finish(false) }).then((attached) => {
      stream = attached;
      if (settled) attached.destroy();
    });
  });
}
