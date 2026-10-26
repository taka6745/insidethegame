import { node } from "../shared/dom.ts";
import { attachStream, captureFrame } from "./media.ts";
import type { Stream, StreamOptions } from "./media.ts";
import { playableClips, reelProgress, reelTimeline, ReplayPlayer } from "./replay.ts";
import type { ReplayAction } from "./replay.ts";
import type { Replay } from "./types.ts";

export interface ReplayStageOptions {
  attach?: (video: HTMLVideoElement, url: string, options: StreamOptions) => Promise<Stream>;
  /** prefers-reduced-motion: no sting and no slow motion. */
  reducedMotion?: () => boolean;
  timers?: { set: (run: () => void, ms: number) => unknown; clear: (id: unknown) => void };
}

/** Replay on the main stage; live shrinks to a muted corner picture and keeps playing. */
export class ReplayStage {
  document: Document;
  attach: NonNullable<ReplayStageOptions["attach"]>;
  player: ReplayPlayer | null = null;
  stream: Stream | null = null;
  opener: HTMLElement | null = null;
  generation = 0;
  loaded = false;
  timeline: ReturnType<typeof reelTimeline> | null = null;
  reducedMotion: () => boolean;
  timers: NonNullable<ReplayStageOptions["timers"]>;
  timer: unknown = null;
  stingTimer: unknown = null;
  url: string | null = null;  // the stream attached to the video
  switching = false;  // a new stream is attaching: the old one's time updates mean nothing
  constructor(document: Document, {
    attach = attachStream,
    reducedMotion = () => Boolean(document.defaultView?.matchMedia?.("(prefers-reduced-motion: reduce)").matches),
    timers = { set: (run, ms) => setTimeout(run, ms), clear: (id) => clearTimeout(id as ReturnType<typeof setTimeout>) },
  }: ReplayStageOptions = {}) {
    this.document = document;
    this.attach = attach;
    this.reducedMotion = reducedMotion;
    this.timers = timers;
    const video = this.video;
    video.addEventListener("timeupdate", () => {
      if (this.switching) return;
      this.apply(this.player?.time(video.currentTime));
      this.pace();
    });
    // Footage that stops short of a clip's out point ends that clip, not the reel.
    video.addEventListener("ended", () => this.apply(this.player?.time(Number.POSITIVE_INFINITY)));
    // Only the first load seeks to the clip: hls.js media recovery reloads metadata mid-clip.
    video.addEventListener("loadedmetadata", () => {
      this.switching = false;
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
    this.opener = opener || null;
    this.player = new ReplayPlayer(clips, replay.playback ?? null, { reducedMotion: this.reducedMotion() });
    this.cueSting();
    this.loaded = false;
    this.timeline = null;
    const video = this.video;
    video.muted = true;
    video.hidden = false;
    this.get("match-stage").dataset.mode = "replay";
    this.get("replay-overlay").hidden = false;
    this.get("pip-return").hidden = false;
    this.show();
    this.get("replay-close").focus?.();
    // The replay plays the match's published stream; clip times are match video seconds.
    this.source(String(clips[0]!.playlist), clips[0]!.playlist_start);
  }
  /** Attach a stream at `start`; a reel across matches switches streams between clips. */
  source(url: string, start: number) {
    const generation = ++this.generation;
    this.stream?.destroy();
    this.stream = null;
    this.url = url;
    this.attach(this.video, url, {
      live: false,
      start,
      onError: () => this.caption("Footage unavailable"),
    }).then((stream) => {
      if (generation !== this.generation) return stream.destroy();
      this.stream = stream;
      if (this.player?.phase === "playing") this.video.play().catch(() => {});
    });
  }
  /** Back to live: restore the stage, release the player and return focus. */
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
    this.wait(null);
    this.sting(undefined);
    this.generation += 1;
    this.stream?.destroy();
    this.stream = null;
    this.url = null;
    this.switching = false;
    this.video.pause();
    this.video.playbackRate = 1;
    this.player = null;
    this.ended(false);
  }
  apply(action?: ReplayAction): void {
    if (!action || !this.player) return;
    // A sting that failed to load would only cover the picture: cut straight to the next clip.
    if (action.sting === "in" && !this.builtin && this.stingVideo.error) return this.apply(this.player.skip());
    const video = this.video;
    const url = this.player.clip?.playlist;
    if (action.seek !== undefined && url && url !== this.url) {
      // The next clip is on another match's stream: cut to it (under the sting when there is one).
      this.switching = true;
      this.source(url, action.seek);
    } else if (action.seek !== undefined && Math.abs(video.currentTime - action.seek) > 0.25) video.currentTime = action.seek;
    if (action.ended || action.pause) video.pause();
    else if ((action.play || action.seek !== undefined) && video.paused) video.play().catch(() => {});
    if (Object.keys(action).length) {  // Time updates return {} and change nothing.
      if (action.sting || this.player.phase !== "sting") this.sting(action.sting);
      this.wait(action.wait ?? null);
    }
    this.pace();
    this.show();
  }
  /** One timer at a time: a new action replaces the last wait. */
  wait(seconds: number | null) {
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = seconds === null ? null : this.timers.set(() => {
      this.timer = null;
      this.apply(this.player?.advance());
    }, seconds * 1000);
  }
  /** Slow motion around the clip's events (the player decides the rate). */
  pace() {
    const rate = this.player?.rate(this.video.currentTime) ?? 1;
    if (Math.abs(this.video.playbackRate - rate) > 0.01) this.video.playbackRate = rate;
  }
  get stingLayer(): HTMLElement {
    return this.get("replay-sting");
  }
  get stingVideo(): HTMLVideoElement {
    return this.get("replay-sting-video") as HTMLVideoElement;
  }
  /** `builtin:league` draws the league's own CSS sting instead of playing a video asset. */
  get builtin(): boolean {
    return this.player?.transitions?.asset.startsWith("builtin:") ?? false;
  }
  /** Loads the sting asset when the reel opens, so it is ready at the first cut. */
  cueSting() {
    const transitions = this.player?.transitions;
    if (!transitions || this.player?.reducedMotion || this.player!.clips.length < 2) return;
    this.stingLayer.style.setProperty("--sting-fade", `${transitions.fade_seconds}s`);
    this.stingLayer.style.setProperty("--sting-length", `${transitions.sting_seconds}s`);
    this.stingLayer.dataset.kind = this.builtin ? "builtin" : "video";
    if (this.builtin) return;
    const video = this.stingVideo;
    if (video.getAttribute("src") !== transitions.asset) {
      video.setAttribute("src", transitions.asset);
      video.preload = "auto";
      // Parked at its start point, so the first frame shown is already the right one.
      video.addEventListener("loadedmetadata", () => this.park(), { once: true });
    }
  }
  /** "in": fade the sting in from its start point; "out": fade it out, then hide it; nothing: hide now. */
  sting(state: "in" | "out" | undefined) {
    const layer = this.stingLayer, video = this.stingVideo;
    const transitions = this.player?.transitions;
    if (this.stingTimer !== null) this.timers.clear(this.stingTimer);
    this.stingTimer = null;
    if (state === "in" && transitions) {
      layer.hidden = false;
      if (!this.builtin) {
        if (Math.abs(video.currentTime - transitions.asset_start_seconds) > 0.05) this.park();
        video.play().catch(() => {});
      }
      void layer.offsetWidth;  // Start the fade from transparent.
      layer.dataset.state = "in";
    } else if (state === "out" && !layer.hidden) {
      layer.dataset.state = "out";
      this.stingTimer = this.timers.set(() => this.sting(undefined), (transitions?.fade_seconds ?? 0) * 1000);
    } else if (!state) {
      layer.dataset.state = "";
      layer.hidden = true;
      video.pause();
      this.park();
    }
  }
  /** The sting video waits at its start point between uses. */
  park() {
    const start = this.player?.transitions?.asset_start_seconds;
    if (start === undefined || this.builtin) return;
    try { this.stingVideo.currentTime = start; } catch { /* not loaded yet: loadedmetadata parks it */ }
  }
  toggle() {
    const player = this.player;
    if (!player) return;
    if (player.phase === "holding" || player.phase === "sting") this.apply(player.skip());
    else if (player.ended) this.apply(player.go(0));
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
    const stage = this.get("match-stage"), changed = stage.dataset.ended !== String(value);
    stage.dataset.ended = String(value);
    this.get("replay-end").hidden = !value;
    this.get("replay-close").hidden = value;
    // Focus follows the control that replaces the one just hidden, once per change.
    if (changed && this.player) this.get(value ? "replay-again" : "replay-close").focus?.();
  }
  caption(text: string) {
    // Rewriting the same text on every time update would make the live region announce it again.
    const caption = this.get("replay-caption");
    if (caption.textContent !== text) caption.textContent = text;
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
}: ReplayStageOptions = {}): Promise<boolean> {
  const clip = playableClips(replay)[0];
  if (!clip) return false;
  return captureFrame(canvas, String(clip.playlist), (clip.playlist_start + clip.playlist_end) / 2, attach);
}
