import test from "node:test";
import assert from "node:assert/strict";
import { MatchApi } from "../match/api.ts";
import type { Fetcher } from "../match/api.ts";
import { MatchController, playlistUntil } from "../match/controller.ts";
import type { ControllerOptions } from "../match/controller.ts";
import { FOLLOW_UNAVAILABLE, FollowController } from "../match/follow.ts";
import type { FollowApi } from "../match/follow.ts";
import { FollowView } from "../match/follow-view.ts";
import { MatchView } from "../match/view.ts";
import { QuestionView } from "../match/chat-view.ts";
import type { Follow, FollowOption, FollowTurn, Replay, Snapshot, Timers } from "../match/types.ts";
import { stub } from "./support.ts";

/** Minimal DOM double with class queries. */
class El {
  [attribute: string]: unknown;
  children: El[] = [];
  dataset: Record<string, string> = {};
  textContent = "";
  className = "";
  hidden = false;
  disabled = false;
  scrollTop = 0;
  scrollHeight = 0;
  clientHeight = 0;
  parent: El | null = null;
  listeners: Record<string, () => void> = {};
  style = { setProperty() {}, removeProperty() {} };
  tag: string;
  constructor(tag: string) { this.tag = tag; }
  append(...items: El[]) { for (const item of items) this.insertBefore(item, null); }
  prepend(item: El) { this.insertBefore(item, this.children[0] || null); }
  insertBefore(item: El, before: El | null) {
    item.remove();
    this.children.splice(before ? this.children.indexOf(before) : this.children.length, 0, item);
    item.parent = this;
  }
  replaceChildren(...items: El[]) { for (const c of [...this.children]) c.remove(); this.append(...items); }
  replaceWith(other: El) { this.parent!.insertBefore(other, this); this.remove(); }
  remove() { if (this.parent) { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; } }
  addEventListener(name: string, fn: () => void) { this.listeners[name] = fn; }
  setAttribute(name: string, value: unknown) { this[name] = value; }
  getAttribute(name: string) { return (this[name] as string | undefined) ?? null; }
  removeAttribute(name: string) { delete this[name]; }
  all(): El[] { return this.children.flatMap((c) => [c, ...c.all()]); }
  querySelectorAll(selector: string) {
    return this.all().filter((c) => selector.startsWith(".") ? c.className.split(" ").includes(selector.slice(1)) : c.tag === selector);
  }
  querySelector(selector: string) { return this.querySelectorAll(selector)[0] ?? null; }
  get text(): string { return this.textContent + this.children.map((c) => c.text).join(""); }
  get isConnected() { return Boolean(this.parent); }
  focus() {}
  set innerHTML(_: string) { throw new Error("Unsafe HTML assignment"); }
}
function dom() {
  const nodes = new Map<string, El>();
  const document = {
    body: new El("body"),
    createElement: (tag: string) => new El(tag),
    getElementById: (id: string) => nodes.get(id) ?? nodes.set(id, new El("div")).get(id)!,
    querySelectorAll: () => [],
  };
  return { document, doc: stub<Document>(document), get: (id: string) => document.getElementById(id) };
}

const spec = { kind: "player" as const, player_id: "riverton-24", team_id: "riverton", focus: "", label: "Sami Lindqvist" };
const follow: Follow = { subscription_id: "s1", topic_id: "topic:a", spec, label: "Sami Lindqvist" };
const option: FollowOption = { id: "topic:a", label: "Sami Lindqvist", spec };
const moments = [
  { id: "km:1", kind: "kick_off", label: "Kick-off", period: 1, clock_seconds: 0 },
  { id: "km:2", kind: "goal", label: "Goal · Riverton Rovers · Sami Lindqvist", period: 1, clock_seconds: 300, minute_label: "5'" },
  { id: "km:3", kind: "goal", label: "Goal · Forgeham United · Theo Marchetti", period: 1, clock_seconds: 420, overturned: true },
];
const state = (version: number, extra: Partial<Snapshot> = {}): Snapshot => ({
  type: "snapshot", projection_epoch: "e", version, cards: [], events: [],
  match: { id: "m", seq: 40, period: 1, clock_seconds: 500, status: "live" },
  narratives: [{ id: "i1", period: 1, clock_seconds: 310, text: "Insight" }],
  feed_mode: "insights", follow: null, key_moments: moments, ...extra,
});
const following = (version: number, narratives: Snapshot["narratives"] = []) => state(version, {
  feed_mode: "following", follow, narratives });

test("follow API: routes, bodies and the shown seq", async () => {
  const calls: Parameters<Fetcher>[] = [];
  const api = new MatchApi(async (...args) => {
    calls.push(args);
    return { ok: true, status: 200, json: async () => ({}) };
  }, "/viewer-api", "m-1");
  await api.follows("t");
  await api.follow("t", spec, 40);
  await api.unfollow("t", "s1");
  await api.followSuggestions("t", 40);
  await api.followSuggestions("t");
  await api.followMessage("t", "follow Lindqvist", "r1", 40);
  const S = "/viewer-api/matches/m-1/sessions/t";
  assert.deepEqual(calls.map(([url, init]) => [init.method, url]), [
    ["GET", `${S}/follows`], ["POST", `${S}/follows`], ["DELETE", `${S}/follows/s1`],
    ["GET", `${S}/follow/suggestions?seq=40`], ["GET", `${S}/follow/suggestions`], ["POST", `${S}/follow/messages`]]);
  assert.deepEqual(JSON.parse(String(calls[1]![1].body)), { spec, seq: 40 });
  assert.deepEqual(JSON.parse(String(calls[5]![1].body)), { prompt: "follow Lindqvist", request_id: "r1", seq: 40 });
});

function setup(api: Partial<FollowApi>) {
  const renders: Snapshot[] = [], statuses: [string, boolean][] = [], actions: boolean[] = [];
  const suggestions: FollowOption[][] = [], turns: FollowTurn[][] = [];
  const timers = stub<Timers>({ setTimeout: () => null, clearTimeout() {} });
  const host = new MatchController(stub<ControllerOptions>({
    api: {}, view: { render: (s: Snapshot) => renders.push(s), error() {}, connection() {}, audience: {} },
    questions: { render() {}, status() {} }, live: { stop() {}, connect() {} },
    storage: { getItem() {}, setItem() {} }, schedule: (fn: () => void) => fn(), timers,
  }));
  host.token = "t";
  const follows = new FollowController({
    api: stub<FollowApi>({ followSuggestions: async () => ({ items: [option] }), follows: async () => ({ turns: [] }), ...api }),
    view: { render: (t: FollowTurn[]) => turns.push(t), status: (...s: [string, boolean]) => statuses.push(s),
      actions: (a: boolean) => actions.push(a), suggestions: (s: FollowOption[]) => suggestions.push(s) },
    host, uuid: () => "uuid", timers,
  });
  return { host, follows, renders, statuses, actions, suggestions, turns };
}

test("following shows the story feed now; stop following restores the insights", async () => {
  const sent: unknown[] = [];
  const f = setup({
    follow: async (...args: unknown[]) => { sent.push(args); return { snapshot: following(3), follow, created: true }; },
    unfollow: async (...args: unknown[]) => { sent.push(args); return { snapshot: state(4) }; },
  });
  f.host.receive(state(2));
  await f.follows.follow(option);
  assert.deepEqual(sent[0], ["t", spec, 40]);
  assert.equal(f.renders.at(-1)!.feed_mode, "following");
  assert.equal(f.renders.at(-1)!.follow?.label, "Sami Lindqvist");
  assert.equal(f.suggestions.length, 1); // refreshed after the change
  await f.follows.unfollow();
  assert.deepEqual(sent[1], ["t", "s1"]);
  assert.equal(f.renders.at(-1)!.feed_mode, "insights");
  assert.equal(f.renders.at(-1)!.follow, null);
  assert.equal(f.follows.busy, false);
});

test("a second follow is refused with the backend's message; actions stay usable", async () => {
  const f = setup({ follow: async () => {
    throw Object.assign(new Error("You already follow a story. Stop following it to choose another."), { status: 409, code: "follow_limit" });
  } });
  await f.follows.follow(option);
  assert.deepEqual(f.statuses.at(-1), ["You already follow a story. Stop following it to choose another.", false]);
  assert.equal(f.actions.at(-1), true);
});

test("without a model the follow chat is unavailable but suggestions still follow", async () => {
  const f = setup({ followMessage: async () => {
    throw Object.assign(new Error("No model"), { status: 503, code: "model_unavailable" });
  }, follow: async () => ({ snapshot: following(3), follow, created: true }) });
  f.host.receive(state(2));
  await f.follows.send("follow the press");
  assert.deepEqual(f.statuses.at(-1), [FOLLOW_UNAVAILABLE, true]);
  assert.equal(f.actions.at(-1), true);
  assert.equal(f.follows.retry, null);
  await f.follows.follow(option);
  assert.equal(f.renders.at(-1)!.feed_mode, "following");
  assert.deepEqual(f.statuses.at(-1), [FOLLOW_UNAVAILABLE, true]);
  f.follows.open({ mode: "unavailable" });
  assert.deepEqual(f.statuses.at(-1), [FOLLOW_UNAVAILABLE, true]);
});

test("a chat turn sends the shown seq, keeps its id for a retry and shows the saved turns", async () => {
  const ids: unknown[] = [];
  let fail = true;
  const saved: FollowTurn[] = [{ request_id: "uuid", prompt: "Lindqvist", status: "done",
    reply: { status: "proposal", text: "Follow Sami Lindqvist?", proposal: option, candidates: [] } }];
  const f = setup({
    followMessage: async (...args: unknown[]) => {
      ids.push(args);
      if (fail) throw Object.assign(new Error("Network"), { status: 502 });
      return { status: "proposal", text: "" };
    },
    follows: async () => ({ follow: null, follows: [], turns: saved }),
  });
  let retried = "";
  f.follows.onRetryPrompt = (prompt) => { retried = prompt; };
  f.host.receive(state(2));
  await f.follows.send("Lindqvist");
  assert.equal(retried, "Lindqvist");
  fail = false;
  f.follows.uuid = () => "other";
  await f.follows.send("Lindqvist");
  assert.deepEqual(ids, [["t", "Lindqvist", "uuid", 40], ["t", "Lindqvist", "uuid", 40]]);
  assert.deepEqual(f.turns.at(-1), saved);
});

test("before anything is shown, suggestions wait and a follow is bounded to kick-off", async () => {
  const asked: unknown[] = [], sent: unknown[] = [];
  const f = setup({ followSuggestions: async (...args: unknown[]) => { asked.push(args); return { items: [option] }; },
    follow: async (...args: unknown[]) => { sent.push(args); return { snapshot: following(3), follow, created: true }; } });
  await f.follows.suggest();
  assert.deepEqual(asked, []);
  await f.follows.follow(option);
  assert.deepEqual(sent[0], ["t", spec, 0]);
});

test("a late follow response cannot change a reconnected session", async () => {
  let resolve!: (value: unknown) => void;
  const f = setup({ follow: () => new Promise((done) => { resolve = done; }) as never });
  f.host.receive(state(2));
  const pending = f.follows.follow(option);
  f.host.generation += 1;
  resolve({ snapshot: following(9) });
  await pending;
  assert.equal(f.renders.at(-1)!.version, 2);
});

test("feed: insights with key moments interleaved oldest first, newest at the bottom; overturned goals marked", () => {
  const { doc, get } = dom();
  const view = new MatchView(doc);
  view.render(state(1));
  const rows = get("narratives").children;
  assert.deepEqual(rows.map((r) => r.className), ["key-moment", "key-moment", "narrative latest", "key-moment overturned"]);
  assert.equal(rows[1]!.querySelector(".key-moment-label")!.textContent, "Goal · Riverton Rovers · Sami Lindqvist");
  assert.equal(get("follow-banner").hidden, true);
  // Insights: the follow chat waits behind Customise.
  assert.equal(get("follow-chat").hidden, true);
  assert.equal(get("follow-open").hidden, false);
  assert.equal(get("story-count").textContent, "1");
});

test("follow view: Customise swaps Insights for the follow chat until Cancel", () => {
  const { doc, get } = dom();
  const view = new MatchView(doc);
  view.followSetup = true;
  view.render(state(1));
  assert.equal(get("follow-chat").hidden, false);
  assert.equal(get("narratives").hidden, true);
  assert.equal(get("follow-open").hidden, true);
  view.followSetup = false;
  view.feed(state(1));
  assert.equal(get("follow-chat").hidden, true);
  assert.equal(get("narratives").hidden, false);
  // Following: the story replaces Insights whatever the setup flag says; Stop following is always there.
  view.followSetup = true;
  view.render(following(1));
  assert.equal(get("follow-chat").hidden, true);
  assert.equal(get("follow-banner").hidden, false);
  assert.equal(get("narratives").hidden, false);
});

test("follow view: another match's story is marked with its teams and outlined, never its score", () => {
  const { doc, get } = dom();
  const view = new MatchView(doc);
  const other = { id: "skybridge-whitmore-1", teams: [{ id: "skybridge", name: "Skybridge City", short_name: "Skybridge", code: "SKC", score: 3 },
    { id: "whitmore", name: "Whitmore Wanderers", short_name: "Whitmore", code: "WHW", branding: { crest_asset_id: "whitmore" } }] };
  view.render({ ...following(1, [{ id: "s1", kind: "subscription", topic_id: "topic:a", period: 1, clock_seconds: 450,
    text: "City press high", other_match: other }]), follow_match: other });
  const story = get("narratives").children.find((r) => /\bnarrative\b/.test(r.className))!;
  assert.match(story.className, /cross-match/);
  const header = story.children[0]!;
  assert.equal(header.className, "other-match");
  assert.deepEqual(header.children.map((c) => c.className), ["other-match-mark", "other-match-name", "other-match-v",
    "other-match-crest", "other-match-name"]);
  assert.equal(header.children.map((c) => c.textContent).join(" ").includes("3"), false);
  assert.equal(get("follow-origin").hidden, false);
  assert.match(get("follow-origin").className, /cross-match/);
});

test("feed: following shows only the story, tagged, with an empty state and key moments", () => {
  const { doc, get } = dom();
  const view = new MatchView(doc);
  view.render(following(1));
  let rows = get("narratives").children;
  assert.equal(rows.at(-1)!.className, "story-empty");
  assert.match(rows.at(-1)!.text, /Following Sami Lindqvist/);
  assert.equal(rows.filter((r) => r.className.startsWith("key-moment")).length, 3);
  assert.equal(get("follow-banner").hidden, false);
  assert.equal(get("follow-chat").hidden, true);
  assert.equal(get("follow-label").textContent, "Sami Lindqvist");
  view.render(following(2, [{ id: "s1", kind: "subscription", topic_id: "topic:a", period: 1, clock_seconds: 450, text: "Lindqvist again" }]));
  rows = get("narratives").children;
  const story = rows.find((r) => r.className.startsWith("narrative"))!;
  assert.equal(story.className, "narrative latest");
  assert.equal(story.querySelector(".narrative-tag")!.textContent, "Sami Lindqvist");
  assert.equal(rows.some((r) => r.className === "story-empty"), false);
});

const playlist: Replay = {
  page: 0, page_size: 12, total_items: 2, page_count: 1, seconds: 24, playlist: "/media/hls/m/live.m3u8",
  clips: [
    { start: 290, end: 302, captions: ["Goal · Riverton Rovers · Sami Lindqvist"], marks: [300], playlist_start: 290, playlist_end: 302 },
    { start: 600, end: 612, captions: ["Red card · Adrien Kovalenko"], marks: [605], playlist_start: 600, playlist_end: 612 },
  ],
};

const goalMoment = { id: "km:2", kind: "goal", period: 1, clock_seconds: 300, minute_label: "5'",
  label: "Goal · Riverton Rovers · Sami Lindqvist", team_id: "riverton", team_name: "Riverton Rovers", player_name: "Sami Lindqvist",
  score: "Riverton Rovers 1–0 Forgeham United" };
const cardMoment = { id: "km:4", kind: "red_card", period: 1, clock_seconds: 605, minute_label: "11'",
  label: "Red card · Adrien Kovalenko", team_id: "forgeham", team_name: "Forgeham United", player_name: "Adrien Kovalenko" };
const captured: Replay = { ...playlist, clips: [{ ...playlist.clips[0]!, source_ids: ["km:2"], moments: [goalMoment] },
  { ...playlist.clips[1]!, source_ids: ["km:4"], moments: [cardMoment] }] };

test("feed: a follower's captured clips sit at their moment with a preview card; play opens the playlist from it", () => {
  const { doc, get } = dom();
  const view = new MatchView(doc);
  const played: Replay[] = [];
  view.onPlaylistPlay = (replay) => played.push(replay);
  const story = [{ id: "s1", kind: "subscription" as const, topic_id: "topic:a", period: 1, clock_seconds: 450,
    text: "Lindqvist again" }];
  view.render(following(1, story));
  assert.equal(get("narratives").querySelectorAll(".capture").length, 0);
  view.render({ ...following(2, story), follow_playlist: captured });
  const rows = get("narratives").children;
  const cards = rows.filter((r) => r.className === "capture");
  assert.equal(cards.length, 2);
  // Oldest first by clock: the goal (300) above the story (450) above the red card (605).
  const at = rows.findIndex((r) => r.className.startsWith("narrative"));
  assert.ok(rows.indexOf(cards[0]!) < at && at < rows.indexOf(cards[1]!));
  const goal = cards[0]!;
  assert.equal(goal.querySelector(".clip-preview-minute")!.textContent, "5'");
  assert.equal(goal.querySelector(".clip-preview-event")!.textContent, "Goal");
  assert.equal(goal.querySelector(".clip-preview-player")!.textContent, "Sami Lindqvist");
  assert.equal(goal.querySelector(".clip-preview-score")!.textContent, "Riverton Rovers 1–0 Forgeham United");
  assert.match(String(goal.querySelector(".capture-play")!["aria-label"]), /Play clip: 5' Goal · Riverton Rovers · Sami Lindqvist/);
  (goal.querySelector(".capture-play")!.listeners.click as () => void)();
  assert.deepEqual(played[0]!.clips.map((c) => c.source_ids), [["km:2"], ["km:4"]]);  // from this clip on
  (cards[1]!.querySelector(".capture-play")!.listeners.click as () => void)();
  assert.deepEqual(played[1]!.clips.map((c) => c.source_ids), [["km:4"]]);
  assert.equal(played[1]!.total_items, 1);
  view.render({ ...state(3), follow_playlist: captured });  // not following: no follow clips
  assert.equal(get("narratives").querySelectorAll(".capture").length, 0);
});

test("feed: Insights shows the bucket's key-event clips for everyone; a followed match's clips carry its header", () => {
  const { doc, get } = dom();
  const view = new MatchView(doc);
  view.render({ ...state(1), moment_playlist: captured });
  assert.equal(get("narratives").querySelectorAll(".capture").length, 2);
  // The captured goal's card replaces its key-moment line; the kick-off and the overturned goal keep theirs.
  const lines = get("narratives").children.filter((r) => r.className.startsWith("key-moment"));
  assert.deepEqual(lines.map((r) => r.querySelector(".key-moment-label")!.textContent),
    ["Kick-off", "Goal · Forgeham United · Theo Marchetti"]);
  const other = { id: "skybridge-whitmore-1", teams: [{ id: "skybridge", name: "Skybridge City" },
    { id: "whitmore", name: "Whitmore" }] };
  view.render({ ...following(2, []), follow_playlist: captured, follow_match: other, moment_playlist: captured });
  const cards = get("narratives").children.filter((r) => r.className.startsWith("capture"));
  assert.equal(cards.length, 2);  // the follow's clips only, not the bucket's
  assert.ok(cards.every((c) => c.className.includes("cross-match") && c.querySelector(".other-match")));
});

test("a held state's playlist keeps only the clips its picture has passed", () => {
  assert.equal(playlistUntil(playlist, null), null);
  assert.equal(playlistUntil(playlist, 301), null);
  const one = playlistUntil(playlist, 400)!;
  assert.deepEqual(one.clips.map((c) => c.captions), [["Goal · Riverton Rovers · Sami Lindqvist"]]);
  assert.equal(one.total_items, 1);
  assert.equal(one.seconds, 12);
  assert.equal(playlistUntil(playlist, 700)!.clips.length, 2);
});

test("reframe bounds this match's clips by its picture, but keeps another match's as the server bounded them", () => {
  const f = setup({});
  const media = { seconds: 350 } as Snapshot["match"]["media"];
  f.host.receive(state(2, { match: { ...state(2).match, media } }));
  f.host.reframe({ ...following(4), follow_playlist: playlist });
  assert.equal(f.renders.at(-1)!.follow_playlist!.clips.length, 1);
  const other = { id: "skybridge-whitmore-1", teams: [] };
  f.host.reframe({ ...following(5), follow_playlist: playlist, follow_match: other });
  assert.equal(f.renders.at(-1)!.follow_playlist!.clips.length, 2);
});

test("follow chat: proposals and candidates follow; only the newest turn acts; text stays text", () => {
  const { doc, get } = dom();
  const view = new FollowView(doc);
  const chosen: FollowOption[] = [];
  view.onFollow = (o) => chosen.push(o);
  const other: FollowOption = { id: "topic:b", label: "Sami Lindqvist (Riverton Rovers)", spec: { ...spec, label: "Sami Lindqvist (Riverton Rovers)" } };
  const unsafe = "<img src=x onerror=alert(1)>";
  view.actions(true);
  view.render([
    { request_id: "1", prompt: unsafe, status: "done", reply: { status: "proposal", text: unsafe, proposal: option } },
    { request_id: "2", prompt: "Lindqvist", status: "done", reply: { status: "clarify", text: "Which Lindqvist?", candidates: [option, other] } },
  ]);
  const messages = get("follow-messages");
  assert.equal(messages.children[0]!.children[0]!.textContent, unsafe);
  const follow = messages.querySelector(".follow-action")!;
  assert.equal(follow.disabled, true); // an older proposal
  const choices = messages.querySelectorAll(".clarification-option");
  assert.equal(choices.length, 2);
  choices[1]!.listeners.click!();
  assert.deepEqual(chosen, [other]);
  view.suggestions([option]);
  const chip = get("follow-suggestions").children[0]!;
  assert.equal(chip.textContent, "Sami Lindqvist");
  chip.listeners.click!();
  assert.equal(chosen.length, 2);
  view.status("Unavailable", true);
  assert.equal(get("follow-input").disabled, true);
  assert.equal(chip.disabled, false);
});

test("answers: a request about both games shows one answer per match, the other match's outlined", () => {
  const { doc } = dom();
  const view = new QuestionView(doc);
  const other = { id: "skybridge-whitmore-1", teams: [{ name: "Skybridge City" }, { name: "Whitmore Wanderers" }] };
  const reply = { status: "answer", text: "From each match.", parts: [
    { status: "answer", text: "Redcastle Town: no goals yet." }, { status: "answer", text: "City 1-0.", other_match: other }] };
  const turn = view.turn(stub({ key: "r9", prompt: "goals from both games", reply, offers: [], clarificationActive: false }));
  const parts = turn.querySelectorAll(".chat-part");
  assert.equal(parts.length, 2);
  assert.doesNotMatch(parts[0]!.className, /cross-match/);
  assert.match(parts[1]!.className, /cross-match/);
});

test("answers: another match's answer is outlined with its teams; a story offer follows only on the click", () => {
  const { doc } = dom();
  const view = new QuestionView(doc);
  const offers: unknown[] = [];
  view.onFollowOffer = (offer) => offers.push(offer);
  const other = { id: "skybridge-whitmore-1", teams: [{ name: "Skybridge City", code: "SKC" }, { name: "Whitmore Wanderers", code: "WHW" }] };
  const reply = { status: "answer", text: "City lead the press.", other_match: other,
    follow_offer: { prompt: "How is City's press going?", other_match: other } };
  const turn = view.turn(stub({ key: "r1", prompt: "How is City's press going?", reply, offers: [], clarificationActive: false }));
  assert.match(turn.className, /cross-match/);
  assert.equal(turn.children[0]!.className, "other-match");
  const card = turn.querySelector(".follow-offer")!;
  assert.equal(offers.length, 0);  // never followed without the click
  (card.children[1] as unknown as { listeners: Record<string, () => void> }).listeners.click!();
  assert.deepEqual(offers, [reply.follow_offer]);
  (card.children[2] as unknown as { listeners: Record<string, () => void> }).listeners.click!();
  const again = view.turn(stub({ key: "r1", prompt: "q", reply, offers: [], clarificationActive: false }));
  assert.equal(again.querySelector(".follow-offer"), null);
  const statAnswer = view.turn(stub({ key: "r2", prompt: "q", reply: { status: "answer", text: "12 shots." }, offers: [],
    clarificationActive: false }));
  assert.equal(statAnswer.querySelector(".follow-offer"), null);
});
