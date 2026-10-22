import type { Playback, Replay, ReplayClip } from "./types.ts";

export type PlayableClip = ReplayClip & { playlist_start: number; playlist_end: number };
/** What the stage does next: seek, pause or play the reel, show or hide the sting, and after `wait`
 * seconds call `advance()`. */
export interface ReplayAction {
  seek?: number;
  ended?: boolean;
  pause?: boolean;
  play?: boolean;
  sting?: "in" | "out";  // otherwise the stage hides any sting at once
  wait?: number;
}
/** playing → (clip end) holding → sting, cut under it → playing; the last clip ends without a sting. */
export type ReelPhase = "playing" | "holding" | "sting" | "ended";

/** Clips the replay playlist can actually show. */
export function playableClips(replay: Replay): PlayableClip[] {
  if (!replay.playlist) return [];
  return replay.clips.filter((clip): clip is PlayableClip =>
    Number.isFinite(clip.playlist_start) && Number.isFinite(clip.playlist_end));
}
export function hasMore(replay: Replay): boolean {
  return replay.page + 1 < pageCount(replay);
}
export function pageCount(replay: Replay): number {
  // Pages fill by rank within 12 clips and 3 minutes, so the server counts them.
  return replay.page_count ?? Math.max(1, Math.ceil(replay.total_items / Math.max(1, replay.page_size)));
}
export function duration(seconds: number): string {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}
function filterText(filter: unknown): string {
  const f = (filter || {}) as { outcome?: unknown; event_types?: unknown };
  const types = Array.isArray(f.event_types) ? f.event_types.join("/") : "event";
  return [f.outcome, types].filter(Boolean).join(" ").replaceAll("_", " ");
}
/** Definition of derived evidence, e.g. "failed pass, then opponent touch within 3 s". */
export function derivedText(derived: Record<string, unknown> | null | undefined): string {
  if (!derived) return "";
  if (typeof derived.description === "string") return derived.description;
  if (!derived.first || !derived.then) return "Derived from match events";
  const team = derived.then_team === "same" ? "same-team" : "opponent";
  const within = Number.isFinite(derived.within_seconds) ? ` within ${derived.within_seconds} s` : "";
  return `${filterText(derived.first)}, then ${team} ${filterText(derived.then)}${within}`;
}

const percent = (fraction: number) => Math.round(Math.min(1, Math.max(0, fraction)) * 1000) / 10;

/** One bar for the whole reel: event marks and clip joins as percentages of total playback. */
export function reelTimeline(clips: PlayableClip[]) {
  const lengths = clips.map((clip) => Math.max(0, clip.playlist_end - clip.playlist_start));
  const total = Math.max(0.001, lengths.reduce((sum, length) => sum + length, 0));
  const offsets = lengths.map((_, index) => lengths.slice(0, index).reduce((sum, length) => sum + length, 0));
  return {
    total,
    offsets,
    marks: clips.flatMap((clip, index) => (clip.marks || []).map((mark) =>
      percent((offsets[index]! + mark - clip.start) / total))),
    joins: offsets.slice(1).map((offset) => percent(offset / total)),
  };
}
/** Reel progress at a playlist time within the current clip. */
export function reelProgress(player: ReplayPlayer, time: number, timeline = reelTimeline(player.clips)): number {
  if (player.ended) return 100;
  const clip = player.clip;
  if (!clip) return 0;
  const within = Math.min(clip.playlist_end, Math.max(clip.playlist_start, time)) - clip.playlist_start;
  return percent((timeline.offsets[player.index]! + within) / timeline.total);
}

/** Playback rate at a playlist time: eased down to `rate` before each marked event, held through it, and
 * eased back up after; 1 away from events, when disabled or under reduced motion. */
export function slowRate(clip: PlayableClip | undefined, time: number, slow: Playback["slow_motion"] | null | undefined): number {
  if (!clip || !slow?.enabled || slow.rate >= 1) return 1;
  let rate = 1;
  for (const mark of clip.marks || []) {
    const at = clip.playlist_start + (mark - clip.start);
    const from = at - slow.before_seconds, until = at + slow.after_seconds;
    const edge = time < from ? from - time : time > until ? time - until : 0;
    const eased = edge === 0 ? 0 : slow.ramp_seconds > 0 ? Math.min(1, edge / slow.ramp_seconds) : 1;
    rate = Math.min(rate, slow.rate + (1 - slow.rate) * eased);
  }
  return Math.round(rate * 100) / 100;
}

/** Clip navigation on the replay playlist timeline: auto-advance with an optional hold and sting between
 * clips, prev/next, end of reel. Timers belong to the stage: a `wait` action means call `advance()` later. */
export class ReplayPlayer {
  clips: PlayableClip[];
  index = 0;
  phase: ReelPhase = "playing";
  playback: Playback | null;
  reducedMotion: boolean;
  cued = false;  // in the sting: the next clip is already cued
  constructor(clips: PlayableClip[], playback: Playback | null = null, { reducedMotion = false } = {}) {
    this.clips = clips;
    this.playback = playback;
    this.reducedMotion = reducedMotion;
  }
  get ended(): boolean {
    return this.phase === "ended";
  }
  get clip(): PlayableClip | undefined {
    return this.clips[this.index];
  }
  get transitions() {
    const transitions = this.playback?.transitions;
    return transitions?.enabled ? transitions : null;
  }
  /** Rate for the stage's video at a playlist time. */
  rate(seconds: number): number {
    return this.reducedMotion || this.phase !== "playing" ? 1 : slowRate(this.clip, seconds, this.playback?.slow_motion);
  }
  caption(): string {
    const clip = this.clip;
    return clip ? `${this.index + 1}/${this.clips.length} · ${(clip.captions || []).join(" / ")}` : "";
  }
  go(index: number): ReplayAction {
    if (!this.clips.length) return { ended: true };
    const covered = this.phase === "sting";
    this.cued = false;
    this.index = Math.min(this.clips.length - 1, Math.max(0, index));
    this.phase = "playing";
    return covered ? { seek: this.clip!.playlist_start, play: true, sting: "out" } : { seek: this.clip!.playlist_start };
  }
  next(): ReplayAction {
    return this.index < this.clips.length - 1 ? this.go(this.index + 1) : this.finish();
  }
  previous(): ReplayAction {
    return this.go(this.index - 1);
  }
  /** Called with the playlist time; at a clip's out point it holds (then stings) or jumps. */
  time(seconds: number): ReplayAction {
    const clip = this.clip;
    if (this.phase !== "playing" || !clip || seconds < clip.playlist_end - 0.05) return {};
    const transitions = this.transitions;
    if (!transitions || this.index === this.clips.length - 1) return this.next();
    this.phase = "holding";
    return { pause: true, wait: transitions.hold_seconds };
  }
  /** The stage's timer for the last `wait` ran out. */
  advance(): ReplayAction {
    const transitions = this.transitions;
    if (this.phase === "holding") {
      if (!transitions || this.reducedMotion || transitions.sting_seconds <= 0) return this.next();
      this.phase = "sting";
      this.cued = false;
      return { sting: "in", wait: transitions.cut_seconds };
    }
    if (this.phase === "sting" && transitions && !this.cued) {
      // Cut under the sting: the next clip waits, paused and covered, until the sting fades out.
      this.cued = true;
      this.index += 1;
      return { seek: this.clip!.playlist_start, pause: true,
        wait: Math.max(0, transitions.sting_seconds - transitions.fade_seconds - transitions.cut_seconds) };
    }
    if (this.phase === "sting") {
      this.phase = "playing";
      return { play: true, sting: "out" };
    }
    return {};
  }
  /** Play/pause from the viewer while holding or stinging skips straight to the next clip. */
  skip(): ReplayAction {
    if (this.phase === "sting" && this.cued) return this.go(this.index);
    return this.phase === "holding" || this.phase === "sting" ? this.next() : {};
  }
  finish(): ReplayAction {
    this.phase = "ended";
    return { ended: true };
  }
}
