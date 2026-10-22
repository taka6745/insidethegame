import { attachStream, liveSource } from "./media.ts";
import { isFinished, isLive } from "./format.ts";
import type { HlsLoader, Stream } from "./media.ts";
import type { MatchState, TimerId, Timers } from "./types.ts";

/** A failed playlist is attached again at most this often. */
export const STREAM_RETRY_MS = 5000;
/** How long a live or finished match's playlist may stay missing or empty (the feed publishes its first segment some
 * seconds after kick-off or a seeded start) before the viewer is told footage is unavailable. Before kick-off it waits. */
export const STREAM_START_WAIT_MS = 45_000;

export interface DemoVideo {
  sync(match: MatchState): void;
  disconnect(): void;
  /** Live HLS playhead in match video seconds, or null when no live picture is playing. */
  playhead(): number | null;
}

// The shared replay clock owns aligned footage; viewers cannot scrub ahead.
export function attachDemoVideo(document: Pick<Document, "getElementById">, {
  reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches || false,
  loader,
  now = () => Date.now(),
  timers = globalThis,
}: { reducedMotion?: boolean; loader?: HlsLoader; now?: () => number; timers?: Timers } = {}): DemoVideo {
  const video = document.getElementById("match-video") as HTMLVideoElement;
  const empty = document.getElementById("video-empty") as HTMLElement;
  let aligned = false;
  let currentMatch: MatchState | null = null;
  let stream: Stream | null = null;
  let streamUrl = "";
  let errored = false;
  let retryAt = 0;
  let streamStart: number | undefined;
  /** Until the playlist first plays: when to stop waiting for it (null before kick-off), and the pending retry. */
  let played = false;
  let waitUntil: number | null = null;
  let retry: TimerId = null;
  const describe = () => video.setAttribute("aria-label",
    video.paused ? "Play match footage" : "Pause match footage");
  const start = async () => {
    try {
      await video.play();
    } catch {
      // A click or keyboard activation can retry after blocked autoplay.
    }
    describe();
  };
  const toggle = () => aligned
    ? (isLive(currentMatch?.status) ? start() : undefined)
    : video.paused ? start() : video.pause();
  const starting = () => !!streamUrl && !played && (waitUntil === null || now() < waitUntil);
  const fail = () => {
    errored = true;
    video.hidden = true;
    empty.hidden = false;
    // A stream still starting shows progress and retries by itself; only then is footage unavailable.
    empty.dataset.state = starting() ? "starting" : "unavailable";
    if (empty.dataset.state === "starting" && retry === null) {
      retry = timers.setTimeout(() => {
        retry = null;
        if (errored && streamUrl) playLive(streamUrl, streamStart);
      }, STREAM_RETRY_MS);
      (retry as { unref?: () => void } | null)?.unref?.();
    }
  };
  // Live HLS: attach once per playlist; retry a failed stream at most every STREAM_RETRY_MS.
  const playLive = (url: string, start?: number) => {
    if (url === streamUrl && (!errored || now() < retryAt)) return;
    stream?.destroy();
    stream = null;
    streamUrl = url;
    streamStart = start;
    errored = false;
    retryAt = now() + STREAM_RETRY_MS;
    video.removeAttribute("src");
    attachStream(video, url, { live: true, start, onError: fail, loader }).then((attached) => {
      if (url === streamUrl && !errored) stream = attached;
      else attached.destroy();
    });
  };
  video.addEventListener("loadeddata", () => {
    errored = false;
    played = true;
    video.hidden = false;
    empty.hidden = true;
    describe();
  });
  video.addEventListener("play", describe);
  video.addEventListener("pause", describe);
  video.addEventListener("error", fail);
  video.addEventListener("click", toggle);
  video.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggle();
    }
  });
  video.tabIndex = 0;
  video.setAttribute("role", "button");
  video.muted = true;
  video.loop = true;
  video.autoplay = !reducedMotion;
  video.preload = "auto";
  // No live stream: show the unavailable state. Footage exists only as published live segments.
  const noLive = () => {
    stream?.destroy();
    stream = null;
    streamUrl = "";
    timers.clearTimeout(retry);
    retry = null;
    video.pause();
    video.removeAttribute("src");
    fail();
  };
  return {
    sync(match) {
      const media = match.media;
      const source = liveSource(media);
      if (!source) return noLive();
      aligned = true;
      currentMatch = match;
      video.loop = false;
      video.setAttribute("aria-label", "Live match footage");
      // The producer owns the live edge; hls.js keeps about three segments behind it.
      // Live: the live edge. Scheduled or finished: the server's playback position, held still,
      // so a viewer arriving after full time sees the final picture and every released insight.
      const running = isLive(match.status);
      if (source.url !== streamUrl) {
        played = false;
        waitUntil = null;
        empty.dataset.state = "starting";
      }
      // The wait for a first segment starts at kick-off (or a seeded start), not while the match is scheduled.
      if (waitUntil === null && (running || isFinished(match.status))) waitUntil = now() + STREAM_START_WAIT_MS;
      // Half a second inside the footage: positioned exactly at its end, the picture is black.
      playLive(source.url, running ? undefined : Math.max(0, (Number(media?.seconds) || 0) - 0.5));
      if (running) start();
      else video.pause();
    },
    disconnect() {
      // Live HLS keeps its own edge; there is no server-clocked footage to pause.
    },
    playhead() {
      // A stall or catch-up seek keeps holding at the current position rather than releasing.
      return streamUrl && !errored && !video.paused && (video.readyState >= 2 || video.currentTime > 0)
        ? video.currentTime : null;
    },
  };
}
