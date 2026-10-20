import type Hls from "hls.js";
import type { MatchMedia } from "./types.ts";

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
}
export const LIVE_PLAYLIST = "/media/hls/live.m3u8";
export const MP4_SOURCE = "/media/simulator.mp4";
const HLS_TYPE = "application/vnd.apple.mpegurl";

/** Live HLS when the producer publishes it; otherwise the aligned MP4 demo. */
export function liveSource(media?: MatchMedia | null): { kind: "hls" | "mp4"; url: string } {
  return media?.live
    ? { kind: "hls", url: media.url || LIVE_PLAYLIST }
    : { kind: "mp4", url: MP4_SOURCE };
}

/** hls.js where Media Source is available; native HLS (Safari) only as the fallback. */
export function playbackEngine(hlsSupported: boolean, nativeSupport: string): Engine {
  if (hlsSupported) return "hls.js";
  return nativeSupport ? "native" : "none";
}

/** Blob URLs cannot resolve relative paths, so root-relative segment URIs become absolute. */
export function absolutePlaylist(text: string, origin: string): string {
  return text.replace(/^\/(?!\/)/gm, `${origin}/`);
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
  if (live) return { ...base, liveSyncDurationCount: 3, liveMaxLatencyDurationCount: 10,
    maxLiveSyncPlaybackRate: 1.1, backBufferLength: 30, ...(start === undefined ? {} : { startPosition: start }) };
  return capture
    ? { ...base, startPosition: start ?? -1, maxBufferLength: 2, maxMaxBufferLength: 4, backBufferLength: 0 }
    : { ...base, startPosition: start ?? -1, maxBufferLength: 12, maxMaxBufferLength: 30, backBufferLength: 10 };
}

export async function attachStream(
  video: HTMLVideoElement,
  url: string,
  { live, start, onError, loader = loadHls, capture = false }: StreamOptions,
): Promise<Stream> {
  const Player = await loader();
  const engine = playbackEngine(Boolean(Player?.isSupported()), video.canPlayType(HLS_TYPE));
  if (engine === "hls.js") {
    const hls = new Player!(streamConfig(live, start, capture));
    let active = true, recoveries = 0;
    const destroy = () => {
      if (active) hls.destroy();
      active = false;
    };
    hls.on(Player!.Events.FRAG_BUFFERED, () => { recoveries = 0; });
    hls.on(Player!.Events.ERROR, (_event, data) => {
      if (!data.fatal) return;
      // A single-level stream escalates stalls and missing segments to fatal; recover in place
      // (keeping the last frame) before giving up, which would blank the picture.
      if (recoveries++ < 3) {
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
