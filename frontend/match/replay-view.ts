import { node } from "./dom.ts";
import { absolutePlaylist, attachStream, captureFrame } from "./media.ts";
import type { Stream, StreamOptions } from "./media.ts";
import { playableClips, reelProgress, reelTimeline, ReplayPlayer } from "./replay.ts";
import type { ReplayAction } from "./replay.ts";
import type { Replay } from "./types.ts";

export interface ReplayStageOptions {
  attach?: (video: HTMLVideoElement, url: string, options: StreamOptions) => Promise<Stream>;
  urls?: Pick<typeof URL, "createObjectURL" | "revokeObjectURL">;
  origin?: string;
}

/** A replay plays the published stream URL; older saved replays carry stitched playlist text. */
function replaySource(replay: Replay, urls: NonNullable<ReplayStageOptions["urls"]>, origin: string) {
  const playlist = String(replay.playlist);
  if (!playlist.startsWith("#EXTM3U")) return { url: playlist, release() {} };
  const url = urls.createObjectURL(new Blob([absolutePlaylist(playlist, origin)],
    { type: "application/vnd.apple.mpegurl" }));
  return { url, release: () => urls.revokeObjectURL(url) };
}

/** Replay on the main stage; live shrinks to a muted corner picture and keeps playing. */
export class ReplayStage {
  document: Document;
  attach: NonNullable<ReplayStageOptions["attach"]>;
  urls: NonNullable<ReplayStageOptions["urls"]>;
  origin: string;
  player: ReplayPlayer | null = null;
  stream: Stream | null = null;
  release = () => {};
  opener: HTMLElement | null = null;
  generation = 0;
  loaded = false;
  timeline: ReturnType<typeof reelTimeline> | null = null;
  constructor(document: Document, {
    attach = attachStream,
    urls = URL,
    origin = globalThis.location?.origin || "",
  }: ReplayStageOptions = {}) {
    this.document = document;
    this.attach = attach;
    this.urls = urls;
    this.origin = origin;
    const video = this.video;
    video.addEventListener("timeupdate", () => this.apply(this.player?.time(video.currentTime)));
    video.addEventListener("ended", () => this.apply(this.player?.finish()));
    // Only the first load seeks to the clip: hls.js media recovery reloads metadata mid-clip.
    video.addEventListener("loadedmetadata", () => {
      if (this.loaded) return;
      this.loaded = true;
      this.apply(this.player?.go(this.player.index));
    });
    video.addEventListener("click", () => this.toggle());  // The picture itself pauses and resumes.
    for (const id of ["replay-close", "pip-return", "replay-live"])
      this.get(id).addEventListener("click", () => this.close());
    this.get("replay-again").addEventListener("click", () => this.toggle());
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.player) this.close();
    });
  }
  get(id: string): HTMLElement {
    return this.document.getElementById(id) as HTMLElement;
  }
  get video(): HTMLVideoElement {
    return this.get("replay-video") as HTMLVideoElement;
  }
  get isOpen() {
    return Boolean(this.player);
  }
  open(replay: Replay, opener?: HTMLElement) {
    const clips = playableClips(replay);
    if (!clips.length) return;
    this.stop();
    const generation = ++this.generation;
    this.opener = opener || null;
    this.player = new ReplayPlayer(clips);
    this.loaded = false;
    this.timeline = null;
    const source = replaySource(replay, this.urls, this.origin);
    this.release = source.release;
    const video = this.video;
    video.muted = true;
    video.hidden = false;
    this.get("match-stage").dataset.mode = "replay";
    this.get("replay-overlay").hidden = false;
    this.get("pip-return").hidden = false;
    this.show();
    this.get("replay-close").focus?.();
    this.attach(video, source.url, {
      live: false,
      start: clips[0]!.playlist_start,
      onError: () => this.caption("Footage unavailable"),
    }).then((stream) => {
      if (generation === this.generation) {
        this.stream = stream;
        video.play().catch(() => {});
      } else stream.destroy();
    });
  }
  /** Back to live: restore the stage, release the playlist and return focus. */
  close() {
    if (!this.player) return;
    this.stop();
    this.get("match-stage").dataset.mode = "live";
    this.get("replay-overlay").hidden = true;
    this.get("pip-return").hidden = true;
    this.video.hidden = true;
    const target = this.opener?.isConnected ? this.opener : this.get("match-video");
    target.focus?.();
    this.opener = null;
  }
  stop() {
    this.generation += 1;
    this.stream?.destroy();
    this.stream = null;
    this.video.pause();
    this.release();
    this.release = () => {};
    this.player = null;
    this.ended(false);
  }
  apply(action?: ReplayAction) {
    if (!action || !this.player) return;
    const video = this.video;
    if (action.seek !== undefined && Math.abs(video.currentTime - action.seek) > 0.25) video.currentTime = action.seek;
    if (action.ended) video.pause();
    else if (action.seek !== undefined && video.paused) video.play().catch(() => {});
    this.show();
  }
  toggle() {
    const player = this.player;
    if (!player) return;
    if (player.ended) this.apply(player.go(0));
    else if (this.video.paused) this.video.play().catch(() => {});
    else this.video.pause();
  }
  /** The stage stays clear: a Replay badge with a clip counter, a progress bar with the event
   * marked in red, and Back to live. Captions are announced, not drawn. At the end the last
   * frame holds, greyed, with Replay and Back to live. */
  show() {
    const player = this.player;
    if (!player) return;
    this.caption(player.ended ? "Replay finished" : player.caption());
    this.get("replay-badge").textContent = player.clips.length > 1
      ? `Replay ${player.index + 1}/${player.clips.length}` : "Replay";
    this.ended(player.ended);
    if (!this.timeline) {
      // Drawn once per reel: a red line per event and a faint tick where clips join.
      this.timeline = reelTimeline(player.clips);
      this.get("replay-marks").replaceChildren(
        ...this.timeline.joins.map((left) => this.tick("replay-join", left)),
        ...this.timeline.marks.map((left) => this.tick("replay-mark", left)));
    }
    this.get("replay-progress-fill").style.width = `${reelProgress(player, this.video.currentTime, this.timeline)}%`;
  }
  tick(className: string, left: number) {
    const line = node(this.document, "span", "", className);
    line.style.left = `${left}%`;
    return line;
  }
  ended(value: boolean) {
    this.get("match-stage").dataset.ended = String(value);
    this.get("replay-end").hidden = !value;
    this.get("replay-close").hidden = value;
    if (value) this.get("replay-again").focus?.();
  }
  caption(text: string) {
    this.get("replay-caption").textContent = text;
  }
}

let stills: Promise<unknown> = Promise.resolve();

/** Stills decode one at a time, once their card is on screen, so they never compete with
 * the live and replay players or download footage for history nobody is looking at. */
export function queueStill(canvas: HTMLCanvasElement, draw: () => Promise<unknown>) {
  const run = () => { stills = stills.then(draw, draw); };
  const Observer = globalThis.IntersectionObserver;
  if (!Observer) return run();
  const observer = new Observer((entries) => {
    if (!entries.some((entry) => entry.isIntersecting)) return;
    observer.disconnect();
    run();
  });
  observer.observe(canvas);
}

/** Chat card still: the middle of the first clip, from the same replay playlist. */
export async function replayStill(replay: Replay, canvas: HTMLCanvasElement, {
  attach = attachStream,
  urls = URL,
  origin = globalThis.location?.origin || "",
}: ReplayStageOptions = {}): Promise<boolean> {
  const clip = playableClips(replay)[0];
  if (!clip) return false;
  const source = replaySource(replay, urls, origin);
  try {
    return await captureFrame(canvas, source.url, (clip.playlist_start + clip.playlist_end) / 2, attach);
  } finally {
    source.release();
  }
}
