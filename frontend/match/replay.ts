import type { Replay, ReplayClip } from "./types.ts";

export type PlayableClip = ReplayClip & { playlist_start: number; playlist_end: number };
export interface ReplayAction {
  seek?: number;
  ended?: boolean;
}

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

/** Clip navigation on the replay playlist timeline: auto-advance, prev/next, end of reel. */
export class ReplayPlayer {
  clips: PlayableClip[];
  index = 0;
  ended = false;
  constructor(clips: PlayableClip[]) {
    this.clips = clips;
  }
  get clip(): PlayableClip | undefined {
    return this.clips[this.index];
  }
  caption(): string {
    const clip = this.clip;
    return clip ? `${this.index + 1}/${this.clips.length} · ${(clip.captions || []).join(" / ")}` : "";
  }
  go(index: number): ReplayAction {
    if (!this.clips.length) return { ended: true };
    this.index = Math.min(this.clips.length - 1, Math.max(0, index));
    this.ended = false;
    return { seek: this.clip!.playlist_start };
  }
  next(): ReplayAction {
    return this.index < this.clips.length - 1 ? this.go(this.index + 1) : this.finish();
  }
  previous(): ReplayAction {
    return this.go(this.index - 1);
  }
  /** Called with the playlist time; returns a jump at a clip's out point. */
  time(seconds: number): ReplayAction {
    const clip = this.clip;
    if (this.ended || !clip || seconds < clip.playlist_end - 0.05) return {};
    return this.next();
  }
  finish(): ReplayAction {
    this.ended = true;
    return { ended: true };
  }
}
