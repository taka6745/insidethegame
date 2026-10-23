import { clubBrand, monogram } from "./branding.ts";
import { node } from "../shared/dom.ts";
import type { OtherMatch } from "./types.ts";

/** The class that outlines content from another live match of the demo (companion.css `.cross-match`). */
export const CROSS_MATCH = "cross-match";

/** A small header naming another match: both crests (monogram when missing) and team names, never the score. */
export function otherMatchHeader(document: Document, other: OtherMatch): HTMLElement {
  const header = node(document, "div", "", "other-match");
  const names = other.teams.map((team) => team.short_name || team.name || "").filter(Boolean);
  header.setAttribute("aria-label", `From ${names.join(" v ")}`);
  header.setAttribute("role", "note");
  other.teams.forEach((team, index) => {
    if (index) header.append(node(document, "span", "v", "other-match-v"));
    const crest = clubBrand(team.branding)?.crest;
    if (crest) {
      const image = node(document, "img", "", "other-match-crest");
      image.alt = "";
      image.src = crest;
      image.addEventListener("error", () => image.replaceWith(
        node(document, "span", monogram(team, team.position || ""), "other-match-mark")), { once: true });
      header.append(image);
    } else header.append(node(document, "span", monogram(team, team.position || ""), "other-match-mark"));
    header.append(node(document, "span", team.short_name || team.name || "", "other-match-name"));
  });
  return header;
}

/** Outline `element` and put the other match's header first; content from the viewer's own match is untouched. */
export function markOtherMatch<T extends HTMLElement>(document: Document, element: T, other?: OtherMatch | null): T {
  if (!other?.teams?.length) return element;
  element.className = `${element.className || ""} ${CROSS_MATCH}`.trim();
  element.dataset.otherMatch = other.id;
  element.prepend(otherMatchHeader(document, other));
  return element;
}
