import { eventName } from "./capture.ts";
import { node } from "../shared/dom.ts";
import { derivedText, duration, hasMore, matchName, pageCount, playableClips } from "./replay.ts";
import type { Replay } from "./types.ts";

export interface ReplayCardActions {
  play(replay: Replay, opener: HTMLElement): void;
  /** Draws a still of the replay into the card's frame. */
  frame?(replay: Replay, canvas: HTMLCanvasElement): unknown;
  page(page: number): Promise<void>;
  refineOffer?: string | null;
  status?: string;
}

/** Chat replay frame: a still with Play, length and paging. Clips play on the main stage. */
export function replayCard(document: Document, replay: Replay, actions: ReplayCardActions): HTMLElement {
  const card = node(document, "section", "", "replay-card");
  card.setAttribute("aria-label", "Replay clips");
  const count = replay.clips.length;
  const playable = playableClips(replay).length > 0;
  const play = node(document, "button", "", "replay-play replay-frame");
  play.setAttribute("aria-label", playable ? `Play ${count} replay ${count === 1 ? "clip" : "clips"} on the main stage` : "Footage unavailable");
  play.disabled = !playable;
  play.addEventListener("click", () => actions.play(replay, play));
  const still = node(document, "canvas", "", "replay-still") as HTMLCanvasElement;
  still.setAttribute("aria-hidden", "true");
  play.append(still, node(document, "span", "▶", "replay-frame-icon"),
    node(document, "span", `${count} ${count === 1 ? "clip" : "clips"} · ${duration(replay.seconds)}`, "replay-frame-meta"));
  // A key moment's preview line: its minute and event, when the clip carries its facts. Chat
  // replays of ordinary events list no captions.
  const moment = replay.clips[0]?.moments?.[0];
  if (moment) play.append(node(document, "span", [moment.minute_label, eventName(moment)].filter(Boolean).join(" · "),
    "replay-frame-caption"));
  card.append(play);
  if (playable) actions.frame?.(replay, still);
  // A reel across matches: each clip named with its game.
  if (replay.clips.some((clip) => matchName(clip.other_match))) {
    const list = node(document, "ol", "", "replay-games");
    for (const clip of replay.clips)
      list.append(node(document, "li", [matchName(clip.other_match), (clip.captions || []).join(" / ")].filter(Boolean).join(" · "),
        "replay-game"));
    card.append(list);
  }
  const derived = derivedText(replay.derived);
  if (derived) card.append(node(document, "p", `Derived: ${derived}`, "replay-note"));
  const refine = replay.refine_offer || actions.refineOffer;
  if (refine) card.append(node(document, "p", refine, "replay-note"));
  const controls = node(document, "div", "", "replay-actions");
  const pageButton = (label: string, page: number, className: string) => {
    const button = node(document, "button", label, className);
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await actions.page(page);
      } finally {
        if (button.isConnected) button.disabled = false;
      }
    });
    controls.append(button);
  };
  if (replay.page > 0) pageButton("Previous", replay.page - 1, "replay-previous text-button");
  if (pageCount(replay) > 1)
    controls.append(node(document, "span", `Page ${replay.page + 1} of ${pageCount(replay)}`, "replay-page"));
  if (hasMore(replay)) pageButton("Show more", replay.page + 1, "replay-more text-button");
  if (controls.children.length) card.append(controls);
  if (!playable) card.append(node(document, "p", "Footage unavailable for these clips.", "replay-unavailable"));
  if (actions.status) card.append(node(document, "p", actions.status, "replay-status"));
  return card;
}
