import { clubBrand, monogram } from "./branding.ts";
import { keyedList, node } from "./dom.ts";
import { isFinished, isLive, matchStatus, number } from "./format.ts";
import { validMatchId } from "./api.ts";
import type { MatchSummary, Team } from "./types.ts";

/** Crest URLs that failed once are not requested again on the next refresh. */
const brokenCrests = new Set<string>();

/** The match picker: one link per listed match; opening one loads `/?match={id}`. */
export class MatchPicker {
  document: Document;
  constructor(document: Document) {
    this.document = document;
  }
  get(id: string): HTMLElement {
    return this.document.getElementById(id) as HTMLElement;
  }
  render(matches: readonly MatchSummary[], now = new Date()) {
    const list = this.get("match-list");
    const shown = matches.filter((match) => validMatchId(match.match_id));
    if (!shown.length) {
      list.replaceChildren(node(this.document, "li",
        "No matches yet. A match appears here about a minute before kick-off.", "match-empty"));
    } else keyedList(list, shown, (match) => match.match_id, (match) => this.row(match));
    this.get("picker-updated").textContent = `Updated ${now.toLocaleTimeString("en-GB")}`;
  }
  notice(message = "") {
    const notice = this.get("picker-notice");
    notice.textContent = message;
    notice.hidden = !message;
  }
  row(match: MatchSummary): HTMLElement {
    const item = node(this.document, "li");
    const link = node(this.document, "a", "", "match-link");
    link.href = `/?match=${encodeURIComponent(match.match_id)}`;
    link.dataset.status = isLive(match.status) ? "live" : isFinished(match.status) ? "finished" : "scheduled";
    const [home = {}, away = {}] = sides(match.teams);
    const centre = node(this.document, "span", "", "picker-centre");
    const scored = home.score != null && away.score != null;
    centre.append(
      node(this.document, "span", scored ? `${number(home.score)} – ${number(away.score)}` : "v", "picker-score"),
      node(this.document, "span", matchStatus(match), "picker-status"),
    );
    link.append(this.team(home, "home"), centre, this.team(away, "away"));
    link.setAttribute("aria-label",
      `${home.name || "Home"} v ${away.name || "Away"}, ${matchStatus(match)}`);
    item.append(link);
    return item;
  }
  team(team: Team, side: "home" | "away"): HTMLElement {
    const element = node(this.document, "span", "", `picker-team ${side}`);
    const brand = clubBrand(team.branding)?.crest;
    const crest = brand && !brokenCrests.has(brand) ? brand : null;
    const mark = crest ? node(this.document, "img") : node(this.document, "span", monogram(team, side), "team-monogram");
    if (crest) {
      const image = mark as HTMLImageElement;
      image.alt = "";
      image.src = crest;
      image.addEventListener("error", () => {
        brokenCrests.add(crest);
        image.replaceWith(node(this.document, "span", monogram(team, side), "team-monogram"));
      });
    }
    element.append(mark, node(this.document, "span", team.short_name || team.name || (side === "home" ? "Home" : "Away")));
    return element;
  }
}

/** Home first, by MA1 position when given. */
export function sides(teams: readonly Team[] = []): Team[] {
  const home = teams.find((team) => team.position === "home");
  const away = teams.find((team) => team.position === "away");
  return home && away ? [home, away] : [...teams];
}
