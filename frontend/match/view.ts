import { clubBrand } from "./clubs.ts";
import { AudienceView } from "./audience-view.ts";
import { node, keyedList } from "./dom.ts";
import {
  clock,
  title,
  number,
  statValue,
  replayControls,
} from "./format.ts";
import type { ConnectionState, Narrative, Snapshot, StatCard } from "./types.ts";
import type { DemoVideo } from "./video.ts";

export class MatchView {
  document: Document;
  onUnpin: (id: string | number) => unknown;
  audience: AudienceView;
  video?: DemoVideo;
  constructor(document: Document) {
    this.document = document;
    this.onUnpin = () => {};
    this.audience = new AudienceView(document);
  }
  get(id: string): HTMLElement {
    return this.document.getElementById(id) as HTMLElement;
  }
  text(id: string, value: string) {
    const element = this.get(id);
    if (element.textContent !== value) element.textContent = value;
  }
  connection(state: ConnectionState) {
    if (state !== 'live') this.video?.disconnect();
    this.audience.connection(state === "live");
    this.document.body.dataset.connection = state;
    const labels: Record<ConnectionState, string> = {
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
  error(message?: string) {
    this.text("notice", message || "");
    this.get("notice").hidden = !message;
  }
  render(snapshot: Snapshot) {
    this.audience.render(snapshot);
    const { match, cards } = snapshot;
    this.video?.sync(match);
    this.document.body.dataset.matchStatus = match.status;
    const teams = match.teams || [];
    for (const [index, side] of ["home", "away"].entries()) {
      const team = teams[index] || {};
      this.text(`${side}-name`, team.name || title(side));
      const brand = clubBrand(team);
      this.get(`${side}-banner`).dataset.club = brand?.theme || "unknown";
      for (const suffix of ["crest", "watermark"]) {
        const image = this.get(`${side}-${suffix}`) as HTMLImageElement;
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
      ["completed", "finished"].includes(String(match.status))
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
      cards.some((card) => card.pinned || card.kind === "custom")
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
        (b.period || 0) - (a.period || 0) ||
        Number(b.clock_seconds) - Number(a.clock_seconds),
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
  stat(card: StatCard, existing?: HTMLElement): HTMLElement {
    const pinned = card.pinned || card.kind === "custom";
    const className = `stat-card ${card.kind}${pinned ? " tracked" : ""}`;
    if (existing && existing.className === className) {
      const label = existing.querySelector<HTMLElement>(".stat-label")!;
      label.textContent = card.label ?? null;
      label.title = String(card.label);
      existing.querySelector(".stat-value")!.textContent = statValue(card);
      const button = existing.querySelector("button");
      if (button)
        button.setAttribute("aria-label", `Stop tracking ${card.label}`);
      return existing;
    }
    const element = node(
      this.document,
      "article",
      "",
      className,
    );
    element.append(
      node(this.document, "span", card.label, "stat-label"),
      node(this.document, "strong", statValue(card), "stat-value"),
    );
    element.querySelector<HTMLElement>(".stat-label")!.title = String(card.label);
    if (pinned) {
      element.append(node(this.document, "span", "TRACKING", "stat-tag"));
      const remove = node(this.document, "button", "×", "unpin");
      remove.setAttribute("aria-label", `Stop tracking ${card.label}`);
      remove.addEventListener("click", () => this.onUnpin(card.pin_id || card.id));
      element.append(remove);
    }
    return element;
  }
  narrative(item: Narrative): HTMLElement {
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
