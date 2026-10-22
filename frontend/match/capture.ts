import { clubBrand } from "./branding.ts";
import { node } from "./dom.ts";
import { markOtherMatch } from "./other-match.ts";
import { playableClips } from "./replay.ts";
import type { ClipMoment, OtherMatch, Replay, Team } from "./types.ts";

/** Captured clips in the feed (PLAN.md §10.2 D6–D7): one row per clip of a moment playlist, at its moment's clock,
 * each with a preview card. Playing one plays the playlist from that clip on, on the main stage (slow motion and
 * the sting come with the replay's `playback`). */
export interface CaptureRow {
  replay: Replay;
  index: number;
}

/** The playlist's clips as feed rows, keyed and clocked by their first moment. */
export function captureRows(replay: Replay | null | undefined): { key: string; at: readonly [number, number]; capture: CaptureRow }[] {
  if (!replay) return [];
  return replay.clips.map((clip, index) => {
    const moment = clip.moments?.[0];
    return { key: `clip:${(clip.source_ids || [String(clip.start)]).join(",")}`,
      at: [moment?.period || 0, Number(moment?.clock_seconds) || 0] as const, capture: { replay, index } };
  });
}

/** The playlist from clip `index` on: the reel the card's Play opens. */
export function fromClip(replay: Replay, index: number): Replay {
  const clips = replay.clips.slice(index);
  return { ...replay, clips, total_items: clips.length,
    seconds: clips.reduce((sum, clip) => sum + clip.end - clip.start, 0) };
}

/** The event's name: the first part of the feed's configured label ("Goal · Chelsea · Palmer" → "Goal"). */
export function eventName(moment: ClipMoment | undefined, caption?: string): string {
  return (moment?.label || caption || "").split(" · ")[0]!.trim();
}

/** A preview card: a league-style gradient from the scoring side's club colour, the minute and event, then the
 * player, team and the score after. Built from the clip's facts, no footage needed. */
export function clipPreview(document: Document, moment: ClipMoment | undefined, teams: readonly Team[],
                            caption?: string): HTMLElement {
  const card = node(document, "div", "", "clip-preview");
  card.setAttribute("aria-hidden", "true");  // the Play button names the clip
  const team = teams.find((t) => t.id && t.id === moment?.team_id);
  const brand = clubBrand(team?.branding);
  card.dataset.club = brand?.primary ? "branded" : "league";
  if (brand?.primary) card.style.setProperty("--clip-club", brand.primary);
  if (brand?.crest) {
    const crest = node(document, "img", "", "clip-preview-crest");
    crest.alt = "";
    crest.src = brand.crest;
    crest.addEventListener("error", () => crest.remove(), { once: true });
    card.append(crest);
  }
  card.append(node(document, "span", moment?.minute_label || "", "clip-preview-minute"),
    node(document, "strong", eventName(moment, caption), "clip-preview-event"));
  const who = moment?.player_name || moment?.team_name;
  if (who) card.append(node(document, "span", who, "clip-preview-player"));
  if (moment?.player_name && moment.team_name) card.append(node(document, "span", moment.team_name, "clip-preview-team"));
  if (moment?.score) card.append(node(document, "span", moment.score, "clip-preview-score"));
  card.append(node(document, "span", "▶", "clip-preview-play"));
  return card;
}

/** One captured clip in the feed: its preview card as a Play button, marked when it is from another match. */
export function captureCard(document: Document, row: CaptureRow, teams: readonly Team[],
                            play: (replay: Replay, opener: HTMLElement) => unknown,
                            other?: OtherMatch | null): HTMLElement {
  const clip = row.replay.clips[row.index]!;
  const moment = clip.moments?.[0];
  const article = node(document, "article", "", "capture");
  const button = node(document, "button", "", "capture-play");
  const playable = playableClips({ ...row.replay, clips: [clip] }).length > 0;
  const name = [moment?.minute_label, moment?.label || clip.captions?.[0]].filter(Boolean).join(" ")
    + (moment?.score ? `, ${moment.score}` : "");  // the card is aria-hidden: the button carries all it shows
  button.setAttribute("aria-label", playable ? `Play clip: ${name}` : `${name}: footage unavailable`);
  button.disabled = !playable;
  button.addEventListener("click", () => play(fromClip(row.replay, row.index), button));
  button.append(clipPreview(document, moment, teams, clip.captions?.[0]));
  article.append(button);
  return markOtherMatch(document, article, other);
}
