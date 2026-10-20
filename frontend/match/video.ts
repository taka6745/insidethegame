import { attachStream, liveSource, MP4_SOURCE } from "./media.ts";
import type { HlsLoader, Stream } from "./media.ts";
import type { MatchState } from "./types.ts";

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
}: { reducedMotion?: boolean; loader?: HlsLoader; now?: () => number } = {}): DemoVideo {
  const video = document.getElementById("match-video") as HTMLVideoElement;
  const empty = document.getElementById("video-empty") as HTMLElement;
  let aligned = false;
  let currentMatch: MatchState | null = null;
  let lastAnchor: string | null = null;
  let stream: Stream | null = null;
  let streamUrl = "";
  let errored = false;
  let retryAt = 0;
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
    ? (currentMatch?.status === "running" ? start() : undefined)
    : video.paused ? start() : video.pause();
  const fail = () => {
    errored = true;
    video.hidden = true;
    empty.hidden = false;
  };
  // Live HLS: attach once per playlist; retry a failed stream at most every five seconds.
  const playLive = (url: string, start?: number) => {
    if (url === streamUrl && (!errored || now() < retryAt)) return;
    stream?.destroy();
    stream = null;
    streamUrl = url;
    errored = false;
    retryAt = now() + 5000;
    video.removeAttribute("src");
    attachStream(video, url, { live: true, start, onError: fail, loader }).then((attached) => {
      if (url === streamUrl && !errored) stream = attached;
      else attached.destroy();
    });
  };
  video.addEventListener("loadeddata", () => {
    errored = false;
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
  // The MP4 is a fallback: request it only once the server says there is no live stream.
  let mp4 = false;
  const useMp4 = (play: boolean) => {
    if (mp4) return;
    mp4 = true;
    video.src = MP4_SOURCE;
    if (play && !reducedMotion) start();
  };
  return {
    sync(match) {
      const media = match.media;
      if (!media?.aligned && !media?.live) return useMp4(true);
      aligned = true;
      currentMatch = match;
      video.loop = false;
      video.setAttribute("aria-label", "Live match footage");
      const source = liveSource(media);
      if (source.kind === "hls") {
        // The producer owns the live edge; hls.js keeps about three segments behind it.
        // Running: the live edge. Ready or finished: the server's playback position, held still,
        // so a viewer arriving after full time sees the final picture and every released insight.
        const running = match.status === "running";
        // Half a second inside the footage: positioned exactly at its end, the picture is black.
        playLive(source.url, running ? undefined : Math.max(0, (Number(media.seconds) || 0) - 0.5));
        if (running) start();
        else video.pause();
        return;
      }
      useMp4(false);
      const anchor = `${match.run_id}:${match.status}:${media.sampled_at ?? media.seconds}`;
      const elapsed = match.status === "running" && Number.isFinite(media.sampled_at)
        ? Math.max(0, (Date.now() - Number(media.sampled_at)) / 1000) : 0;
      const target = Math.max(0, Number(media.seconds) || 0) + elapsed;
      if (anchor !== lastAnchor && (Math.abs((video.currentTime || 0) - target) > 1.5 || match.status !== "running"))
        video.currentTime = target;
      lastAnchor = anchor;
      if (match.status === "running") start();
      else video.pause();
    },
    disconnect() {
      // Live HLS keeps its own edge; only server-clocked MP4 footage waits for the socket.
      if (aligned && !streamUrl) {
        video.pause();
        lastAnchor = null;
      }
    },
    playhead() {
      return streamUrl && !errored && !video.paused && video.readyState >= 2
        ? video.currentTime : null;
    },
  };
}
