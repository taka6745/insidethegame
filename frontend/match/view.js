import { clubBrand } from "./clubs.js";
import { node, keyedList } from "./dom.js";
import {
  clock,
  title,
  number,
  replayControls,
} from "./format.js";

export class MatchView {
  constructor(document) {
    this.document = document;
    this.onUnpin = () => {};
  }
  get(id) {
    return this.document.getElementById(id);
  }
  text(id, value) {
    const element = this.get(id);
    if (element.textContent !== value) element.textContent = value;
  }
  profiles(profiles, selected) {
    this.get("profile").replaceChildren(
      ...profiles.map((profile) => {
        const option = node(this.document, "option", profile.display_name);
        option.value = profile.id;
        return option;
      }),
    );
    if (profiles.some((profile) => profile.id === selected))
      this.get("profile").value = selected;
    return this.get("profile").value;
  }
  connection(state) {
    this.document.body.dataset.connection = state;
    const labels = {
      connecting: "Opening your match…",
      live: "",
      reconnecting: "Reconnecting · showing last received state",
      stale: "Connection interrupted · values may be stale",
      offline: "Offline · reconnect to update",
      replaced: "Session ended · another tab or a new demo took over",
    };
    this.text("connection", labels[state] ?? state);
    this.get("inside-the-game").hidden = state === "live";
    this.get("connection").dataset.state = state;
    this.get("reconnect").hidden = !["offline", "replaced", "stale"].includes(
      state,
    );
  }
  error(message) {
    this.text("notice", message || "");
    this.get("notice").hidden = !message;
  }
  render(snapshot) {
    const { match, cards } = snapshot;
    this.document.body.dataset.matchStatus = match.status;
    const teams = match.teams || [];
    for (const [index, side] of ["home", "away"].entries()) {
      const team = teams[index] || {};
      this.text(`${side}-name`, team.name || title(side));
      const brand = clubBrand(team);
      this.get(`${side}-banner`).dataset.club = brand?.theme || "unknown";
      for (const suffix of ["crest", "watermark"]) {
        const image = this.get(`${side}-${suffix}`);
        image.hidden = !brand;
        if (brand) image.src = `/assets/league/clubs/${brand.asset}.svg`;
        else image.removeAttribute("src");
      }
      this.get(`${side}-mark`).hidden = Boolean(brand);
      this.text(`${side}-mark`, (team.name || side).slice(0, 3).toUpperCase());
      this.text(`${side}-score`, number(team.score));
    }
    this.text(
      "match-clock",
      ["completed", "finished"].includes(match.status)
        ? `FT · ${clock(match.clock_seconds)}`
        : clock(match.clock_seconds),
    );
    const [support, style] = (snapshot.bucket || "neutral:casual").split(":");
    const supportName =
      teams.find((team) => team.id === support)?.name || title(support);
    this.text(
      "perspective",
      `${supportName} · ${title(style)}`,
    );
    this.text(
      "stats-context",
      cards.some((card) => card.kind === "custom")
        ? "Includes your tracked stats"
        : "",
    );
    keyedList(
      this.get("stats"),
      cards,
      (card) => card.id,
      (card, existing) => this.stat(card, existing),
    );
    const narratives = [...snapshot.narratives].sort(
      (a, b) =>
        (b.period || 0) - (a.period || 0) || b.clock_seconds - a.clock_seconds,
    );
    this.text("story-count", String(narratives.length));
    if (narratives.length)
      keyedList(
        this.get("narratives"),
        narratives,
        (item) => item.id,
        (item) => this.narrative(item),
      );
    else if (this.get("narratives").querySelector(".narrative")) {
      const empty = node(this.document, "div", "", "story-empty");
      empty.append(
        node(this.document, "h3", "Waiting for kick-off."),
        node(
          this.document,
          "p",
          "Your match insights will appear here.",
        ),
      );
      this.get("narratives").replaceChildren(empty);
    }
    const controls = replayControls(match);
    this.get("start-demo").hidden = !controls.showStart;
    this.text("start-demo-label", controls.startLabel);
    this.get("reset-demo").hidden = !controls.showReset;
  }
  stat(card, existing) {
    if (existing && existing.className === `stat-card ${card.kind}`) {
      existing.querySelector(".stat-label").textContent = card.label;
      existing.querySelector(".stat-label").title = card.label;
      existing.querySelector(".stat-value").textContent = number(card.value);
      const button = existing.querySelector("button");
      if (button)
        button.setAttribute("aria-label", `Stop tracking ${card.label}`);
      return existing;
    }
    const element = node(
      this.document,
      "article",
      "",
      `stat-card ${card.kind}`,
    );
    element.append(
      node(this.document, "span", card.label, "stat-label"),
      node(this.document, "strong", number(card.value), "stat-value"),
    );
    element.querySelector(".stat-label").title = card.label;
    if (card.kind === "custom") {
      element.append(node(this.document, "span", "TRACKING", "stat-tag"));
      const remove = node(this.document, "button", "×", "unpin");
      remove.setAttribute("aria-label", `Stop tracking ${card.label}`);
      remove.addEventListener("click", () => this.onUnpin(card.id));
      element.append(remove);
    }
    return element;
  }
  narrative(item) {
    const article = node(this.document, "article", "", "narrative");
    article.append(
      node(
        this.document,
        "time",
        clock(item.clock_seconds),
      ),
      node(this.document, "p", item.text),
    );
    return article;
  }
}
