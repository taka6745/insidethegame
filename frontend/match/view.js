import { clubBrand } from "./clubs.js";
import { node, keyedList } from "./dom.js";
import {
  clock,
  title,
  number,
  eventLabel,
  latestEvents,
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
      live: "Connected · live updates",
      reconnecting: "Reconnecting · showing last received state",
      stale: "Connection interrupted · values may be stale",
      offline: "Offline · reconnect to update",
      replaced: "Session ended · another tab or a new demo took over",
    };
    this.text("connection", labels[state] || state);
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
    this.text("bucket", `${supportName} · ${title(style)}`);
    this.text(
      "perspective",
      `${title(style)} insights · ${supportName} perspective`,
    );
    this.text(
      "stage-status",
      match.status === "running"
        ? "MATCH IN PROGRESS"
        : match.position
          ? "LATEST RECEIVED MOMENT"
          : "AWAITING KICKOFF",
    );
    this.text(
      "stats-context",
      cards.some((card) => card.kind === "custom")
        ? "Your tracked stats + match picks"
        : "Chosen for your perspective",
    );
    keyedList(
      this.get("stats"),
      cards,
      (card) => card.id,
      (card, existing) => this.stat(card, existing),
    );
    const events = latestEvents(snapshot.events);
    if (events.length) {
      const latest = events[0];
      this.text(
        "event-minute",
        `${clock(latest.match_time_seconds)} · ${latest.team_name || title(latest.team_id)}`,
      );
      this.text("event-title", eventLabel(latest));
      this.text(
        "event-detail",
        `${latest.player_name || title(latest.player_id) || latest.team_name || title(latest.team_id)}${latest.outcome ? ` · ${title(latest.outcome)}` : ""}`,
      );
      keyedList(
        this.get("events"),
        events,
        (event) => event.event_id,
        (event) => this.event(event),
      );
    } else {
      this.text("event-minute", "PRE-MATCH");
      this.text("event-title", "Waiting for kick-off");
      this.text("event-detail", "The latest match event will appear here.");
      this.get("events").replaceChildren(
        node(
          this.document,
          "li",
          "The first event will appear at kickoff.",
          "empty",
        ),
      );
    }
    this.text("event-count", `${snapshot.events.length} recent events`);
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
        node(this.document, "h3", "The story starts here."),
        node(
          this.document,
          "p",
          "As play develops, insights for your team and fan style will arrive here.",
        ),
      );
      this.get("narratives").replaceChildren(empty);
    }
    const controls = replayControls(match);
    this.get("start-demo").hidden = !controls.showStart;
    this.text("start-demo-label", controls.startLabel);
    this.get("reset-demo").hidden = !controls.showReset;
    this.text("demo-progress", controls.progress);
  }
  stat(card, existing) {
    if (existing && existing.className === `stat-card ${card.kind}`) {
      existing.querySelector(".stat-label").textContent = card.label;
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
    if (card.kind === "custom") {
      element.append(node(this.document, "span", "TRACKING", "stat-tag"));
      const remove = node(this.document, "button", "×", "unpin");
      remove.setAttribute("aria-label", `Stop tracking ${card.label}`);
      remove.addEventListener("click", () => this.onUnpin(card.id));
      element.append(remove);
    }
    return element;
  }
  event(event) {
    const item = node(this.document, "li", "", `event-row ${event.event_type}`);
    item.append(
      node(this.document, "time", clock(event.match_time_seconds)),
      node(this.document, "span", "", "event-indicator"),
      node(
        this.document,
        "strong",
        `${eventLabel(event)} · ${event.player_name || title(event.player_id) || event.team_name || title(event.team_id)}`,
      ),
      node(this.document, "small", event.team_name || title(event.team_id)),
    );
    return item;
  }
  narrative(item) {
    const article = node(this.document, "article", "", "narrative");
    article.append(
      node(
        this.document,
        "time",
        `${clock(item.clock_seconds)} · MATCH INSIGHT`,
      ),
      node(this.document, "p", item.text),
    );
    return article;
  }
}
