import { applyBrand, clubBrand, monogram, teamBranding } from "./branding.ts";
import { AudienceView } from "./audience-view.ts";
import { node, keyedList } from "./dom.ts";
import { markOtherMatch } from "./other-match.ts";
import { captureCard, captureRows } from "./capture.ts";
import type { CaptureRow } from "./capture.ts";
import {
  clock,
  countdown,
  isFinished,
  title,
  number,
  statValue,
} from "./format.ts";
import type { ConnectionState, KeyMoment, Narrative, OtherMatch, Replay, Snapshot, StatCard, Team } from "./types.ts";

/** One feed line: a narrative, a key moment, a captured clip or the empty state. */
interface FeedRow {
  key: string;
  at?: readonly [number, number];
  narrative?: Narrative;
  tag?: string;
  moment?: KeyMoment;
  capture?: CaptureRow;
  /** The other match a captured clip is from (it changes the card, so it is part of the row). */
  origin?: string;
  empty?: [string, string];
  /** The line where the viewer began following: catch-up above, live below. */
  since?: string;
}
import type { DemoVideo } from "./video.ts";

export class MatchView {
  document: Document;
  onUnpin: (id: string | number) => unknown;
  /** Plays a captured clip's playlist from that clip on, on the main stage, as a chat replay does. */
  onPlaylistPlay: (replay: Replay, opener: HTMLElement) => unknown = () => {};
  audience: AudienceView;
  video?: DemoVideo;
  /** Teams from the match listing: branding when the snapshot omits it. */
  teams: Team[] = [];
  /** The follow view is open for setting up a follow: its chat replaces Insights until Cancel or a follow. */
  followSetup = false;
  /** A scheduled match's kickoff (null when unknown); undefined once play has started. */
  kickoff?: string | null;
  private brokenCrests = new Set<string>();
  constructor(document: Document) {
    this.document = document;
    this.onUnpin = () => {};
    this.audience = new AudienceView(document);
    // A crest file that is missing falls back to the monogram.
    for (const side of ["home", "away"]) {
      const crest = this.get(`${side}-crest`);
      crest?.addEventListener?.("error", () => {
        this.brokenCrests.add(String(crest.getAttribute("src")));
        for (const suffix of ["crest", "watermark"]) this.get(`${side}-${suffix}`).hidden = true;
        this.get(`${side}-mark`).hidden = false;
      });
    }
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
      waiting: "Not open yet · this match opens about a minute before kick-off",
      gone: "This match is no longer available",
    };
    this.text("connection", labels[state] ?? state);
    this.get("inside-the-game").hidden = state === "live";
    this.get("connection").dataset.state = state;
    this.get("reconnect").hidden = !["offline", "replaced", "stale"].includes(
      state,
    );
  }
  /** Advance the pre-match countdown; live play is clocked by snapshots instead. */
  tick(now = Date.now()) {
    if (this.kickoff !== undefined) this.text("match-clock", countdown(this.kickoff, now));
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
      const brand = clubBrand(teamBranding(team, this.teams));
      applyBrand(this.get(`${side}-banner`), brand);
      const crest = brand?.crest && !this.brokenCrests.has(brand.crest) ? brand.crest : null;
      for (const suffix of ["crest", "watermark"]) {
        const image = this.get(`${side}-${suffix}`) as HTMLImageElement;
        image.hidden = !crest;
        if (crest) {
          if (image.getAttribute("src") !== crest) image.src = crest;
        } else image.removeAttribute("src");
      }
      this.get(`${side}-mark`).hidden = Boolean(crest);
      this.text(`${side}-mark`, monogram(team, side));
      this.text(`${side}-score`, number(team.score));
    }
    this.kickoff = match.status === "scheduled" ? match.scheduled_kickoff ?? null : undefined;
    if (this.kickoff !== undefined) this.tick();
    else this.text(
      "match-clock",
      isFinished(match.status)
        ? `FT · ${clock(match.clock_seconds)}`
        : clock(match.clock_seconds),
    );
    this.text("perspective", this.audience.label(snapshot) || "Your match companion");
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
    this.feed(snapshot);
  }
  /** Insights or the followed story, interleaved by clock with the pivotal key moments (oldest first, newest at the
   * bottom; the list follows the newest unless the viewer has scrolled up). */
  feed(snapshot: Snapshot) {
    const follow = snapshot.feed_mode === "following" ? snapshot.follow ?? null : null;
    // Insights, the follow view while a follow is set up (its chat replaces Insights, Cancel always there), or
    // the followed story (Stop following always there).
    const setup = !follow && this.followSetup;
    this.get("follow-banner").hidden = !follow;
    this.get("follow-chat").hidden = !setup;
    this.get("follow-open").hidden = Boolean(follow) || setup;
    this.get("narratives").hidden = setup;
    const origin = this.get("follow-origin");
    origin.replaceChildren();
    if (follow && snapshot.follow_match) markOtherMatch(this.document, origin, snapshot.follow_match);
    origin.hidden = !(follow && snapshot.follow_match);
    this.text("follow-label", follow?.label || "");
    const tag = follow?.label;
    // A followed story from another match: its clips carry that match's crests and header.
    const other = follow ? snapshot.follow_match ?? null : null;
    const at = (item: { period?: number | null; clock_seconds?: number | null }) =>
      [item.period || 0, Number(item.clock_seconds) || 0] as const;
    // Captured clips (PLAN.md §10.2 D6–D7): the followed story's, or else the bucket's key-event clips.
    const captures = captureRows(follow ? snapshot.follow_playlist : snapshot.moment_playlist);
    // A clip's card shows its moment's line (minute, event, player, score), so this match's line is not repeated.
    const captured = new Set(other ? [] : captures.flatMap((row) =>
      row.capture.replay.clips[row.capture.index]!.source_ids || []));
    const rows: FeedRow[] = [
      ...snapshot.narratives.map((item): FeedRow => ({ key: `n:${item.id}`, at: at(item), narrative: item,
        tag: item.kind === "subscription" ? tag : undefined })),
      ...(snapshot.key_moments || []).filter((moment) => moment.overturned || !captured.has(moment.id))
        .map((moment): FeedRow => ({ key: `m:${moment.id}`, at: at(moment), moment })),
      ...captures.map((row): FeedRow => ({ ...row, origin: other?.id })),
    ];
    if (follow?.since_clock_seconds != null) rows.push({ key: `since:${follow.topic_id}`,
      at: [follow.since_period || 0, follow.since_clock_seconds],
      since: `Following since ${Math.floor(follow.since_clock_seconds / 60) + 1}′` });
    const rank = (row: FeedRow) => row.since ? 3 : row.moment ? 2 : row.capture ? 1 : 0;  // same clock: story, clip, moment
    rows.sort((a, b) => a.at![0] - b.at![0] || a.at![1] - b.at![1] || rank(a) - rank(b));
    this.text("story-count", String(snapshot.narratives.length));
    if (!snapshot.narratives.length) rows.push(follow
      ? { key: `empty:following:${follow.topic_id}`, empty: [`Following ${follow.label}.`, "Updates land here."] }
      : snapshot.match.status === "scheduled" || snapshot.match.clock_seconds == null
        ? { key: "empty:kickoff", empty: ["Waiting for kick-off.", "Insights appear here."] }
        : { key: "empty:insights", empty: ["Insights on the way.", "Insights appear here."] });
    const teams = other?.teams || snapshot.match.teams || [];
    const list = this.get("narratives");
    // Stay on the newest item unless the viewer scrolled up to read older ones.
    const pinned = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    keyedList(list, rows, (row) => row.key, (row) => this.row(row, teams, other));
    const stories = [...list.children].filter((child) => /^narrative\b/.test(child.className)) as HTMLElement[];
    stories.forEach((story, index) => {
      const base = story.className.replace(/\s*\blatest\b/g, "");
      story.className = index === stories.length - 1 ? `${base} latest` : base;
    });
    if (pinned) list.scrollTop = list.scrollHeight;
  }
  row(row: FeedRow, teams: readonly Team[] = [], other: OtherMatch | null = null): HTMLElement {
    if (row.capture)
      return captureCard(this.document, row.capture, teams, (replay, opener) => this.onPlaylistPlay(replay, opener), other);
    if (row.moment) {
      const { label, minute_label, overturned } = row.moment;
      const line = node(this.document, "p", "", `key-moment${overturned ? " overturned" : ""}`);
      if (minute_label) line.append(node(this.document, "span", `${minute_label} `, "sr-only"));
      line.append(node(this.document, "span", label, "key-moment-label"));
      if (overturned) line.append(node(this.document, "span", " (overturned by VAR)", "sr-only"));
      line.title = minute_label || "";
      return line;
    }
    if (row.narrative) return this.narrative(row.narrative, row.tag);
    if (row.since) return node(this.document, "p", row.since, "follow-since");
    const empty = node(this.document, "div", "", "story-empty");
    empty.append(node(this.document, "h3", row.empty?.[0]), node(this.document, "p", row.empty?.[1]));
    return empty;
  }
  stat(card: StatCard, existing?: HTMLElement): HTMLElement {
    const pinned = card.pinned || card.kind === "custom";
    const className = `stat-card ${card.kind}${pinned ? " tracked" : ""}`;
    if (existing && existing.className === className && !card.other_match) {
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
    return markOtherMatch(this.document, element, card.other_match);
  }
  narrative(item: Narrative, tag?: string): HTMLElement {
    const article = node(this.document, "article", "", "narrative");
    article.append(node(this.document, "time", clock(item.clock_seconds)));
    if (tag) article.append(node(this.document, "span", tag, "narrative-tag"));
    article.append(node(this.document, "p", item.text));
    return markOtherMatch(this.document, article, item.other_match);
  }
}
