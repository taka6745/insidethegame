import test from "node:test";
import assert from "node:assert/strict";
import { keyedList } from "../shared/dom.ts";
import { QuestionView } from "../match/chat-view.ts";
import { MatchView } from "../match/view.ts";
import { AudienceView } from "../match/audience-view.ts";
import type { ChatSession, Replay, StatCard } from "../match/types.ts";
import { stub } from "./support.ts";

/** Minimal DOM double: setAttribute stores attributes as properties for assertions. */
class Element {
  [attribute: string]: unknown;
  tag: string;
  children: Element[];
  dataset: Record<string, string>;
  textContent: string;
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
  listeners: Record<string, () => void>;
  parent?: Element | null;
  className?: string;
  value?: string;
  disabled?: boolean;
  focused?: boolean;
  constructor(tag: string) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.textContent = "";
    this.scrollTop = 20;
    this.scrollHeight = 1000;
    this.clientHeight = 300;
    this.listeners = {};
  }
  append(...children: Element[]) {
    for (const child of children) this.insertBefore(child, null);
  }
  prepend(child: Element) {
    this.insertBefore(child, this.children[0] || null);
  }
  insertBefore(child: Element, before: Element | null) {
    child.remove();
    const index = before ? this.children.indexOf(before) : this.children.length;
    this.children.splice(index, 0, child);
    child.parent = this;
  }
  replaceChildren(...children: Element[]) {
    for (const child of [...this.children]) child.remove();
    this.append(...children);
  }
  replaceWith(other: Element) {
    this.parent!.insertBefore(other, this);
    this.remove();
  }
  remove() {
    if (this.parent) {
      this.parent.children.splice(this.parent.children.indexOf(this), 1);
      this.parent = null;
    }
  }
  addEventListener(name: string, fn: () => void) {
    this.listeners[name] = fn;
  }
  removeAttribute(name: string) {
    delete this[name];
  }
  setAttribute(name: string, value: unknown) {
    this[name] = value;
  }
  getAttribute(name: string) {
    return (this[name] as string | undefined) ?? null;
  }
  style = {
    props: {} as Record<string, string>,
    setProperty(name: string, value: string) { this.props[name] = value; },
    removeProperty(name: string) { delete this.props[name]; },
  };
  querySelector(selector: string): Element | null {
    for (const child of this.children) {
      if (
        selector.startsWith(".")
          ? child.className?.split(" ").includes(selector.slice(1))
          : child.tag === selector
      )
        return child;
      const nested = child.querySelector(selector);
      if (nested) return nested;
    }
    return null;
  }
  get isConnected() {
    return Boolean(this.parent);
  }
  focus() {
    this.focused = true;
  }
  set innerHTML(value: string) {
    throw new Error("Unsafe HTML assignment");
  }
}
function documentStub() {
  const nodes = new Map<string, Element>();
  const document = {
    body: new Element("body"),
    activeElement: null as Element | null,
    createElement: (tag: string) => new Element(tag),
    getElementById: (id: string): Element => {
      if (!nodes.has(id)) nodes.set(id, new Element("div"));
      return nodes.get(id)!;
    },
    querySelectorAll: () => [],
  };
  return document;
}
const asDocument = (document: ReturnType<typeof documentStub>) => stub<Document>(document);
const asElement = (element: Element) => stub<HTMLElement>(element);
const fromElement = (element: HTMLElement | null) => stub<Element>(element);
test("unchanged keyed feed entries retain DOM identity and preserve user scroll", () => {
  const container = new Element("div"),
    render = (row: { text: string }) =>
      asElement(Object.assign(new Element("article"), { textContent: row.text }));
  keyedList(
    asElement(container),
    [
      { id: "one", text: "First" },
      { id: "two", text: "Second" },
    ],
    (row) => row.id,
    render,
  );
  const original = container.children[0];
  keyedList(
    asElement(container),
    [
      { id: "new", text: "Latest" },
      { id: "one", text: "First" },
    ],
    (row) => row.id,
    render,
  );
  assert.equal(container.children[1], original);
  assert.equal(container.children.length, 2);
  assert.equal(container.scrollTop, 20);
});
test("model text, prompts and offer labels are text only; scrolled chat does not jump", () => {
  const document = documentStub(),
    view = new QuestionView(asDocument(document)),
    unsafe = "<img src=x onerror=alert(1)>";
  view.render({
    mode: "local",
    turns: [
      {
        id: "turn",
        prompt: unsafe,
        reply: {
          text: unsafe,
          snapshot: { clock_seconds: 100 },
          offers: [{ id: "offer", label: unsafe, value: 3 }],
        },
      },
    ],
  });
  const messages = document.getElementById("chat-messages"),
    turn = messages.children[0]!;
  assert.equal(turn.children[0]!.textContent, unsafe);
  assert.equal(turn.children[1]!.textContent, unsafe);
  assert.equal(turn.children[2]!.children[0]!.textContent, unsafe);
  assert.equal(turn.querySelector(".answer-time")!.textContent, "1′");
  assert.equal(turn.querySelector(".answer-time")!["aria-label"], "Answer as of 1:40");
  assert.equal(messages.scrollTop, 20);
});
test("an answer whose data trails the watched picture by over 10 s names its exact clock", () => {
  const document = documentStub(),
    view = new QuestionView(asDocument(document));
  view.askedAt.set("late", 3400);
  view.askedAt.set("close", 3305);
  view.render({
    turns: ["late", "close"].map((request_id) => ({
      request_id, prompt: "Any goals?", reply: { text: "No goal so far.", snapshot: { clock_seconds: 3300 } },
    })),
  });
  const stamps = document.getElementById("chat-messages").children.map((t) => t.querySelector(".answer-time")!.textContent);
  assert.deepEqual(stamps, ["as of 55:00", "55′"]);
});
test("question history is capped at fifty turns and unchanged Track button retains identity", () => {
  const document = documentStub(),
    view = new QuestionView(asDocument(document));
  const session: ChatSession = {
    turns: Array.from({ length: 100 }, (_, id) => ({
      id,
      prompt: "question",
      reply: {
        text: "answer",
        offers: [{ id: `offer-${id}`, label: "Shots", value: 3 }],
      },
    })),
  };
  view.render(session);
  const messages = document.getElementById("chat-messages");
  assert.equal(messages.children.length, 50);
  const prior = messages.children[0];
  view.render(session);
  assert.equal(messages.children[0], prior);
});

test("changing a live custom value preserves the focused Stop tracking control", () => {
  const document = documentStub(),
    view = new MatchView(asDocument(document)),
    container = new Element("section");
  const card: StatCard = {
    id: "custom-rule",
    kind: "custom",
    label: "Headed shots",
    value: 1,
  };
  keyedList(
    asElement(container),
    [card],
    (row) => row.id,
    (row, existing) => view.stat(row, existing),
  );
  const button = container.children[0]!.querySelector("button");
  document.activeElement = button;
  keyedList(
    asElement(container),
    [{ ...card, value: 2 }],
    (row) => row.id,
    (row, existing) => view.stat(row, existing),
  );
  assert.equal(
    container.children[0]!.querySelector("button"),
    document.activeElement,
  );
  assert.equal(
    container.children[0]!.querySelector(".stat-value")!.textContent,
    "2",
  );
});

test("audience dropdown lists only the match's enabled buckets and keeps the selection across updates", () => {
  const document = documentStub();
  const view = new AudienceView(asDocument(document));
  const select = () => fromElement(view.select), controls = () => fromElement(view.controls);
  const state = {audience: {bucket_id: "away:experienced", selections: {team: "away", fan_style: "experienced"}},
    audience_buckets: [{id: "home:simple", label: "Riverton Rovers · Simple"}, {id: "away:experienced", label: "Forgeham United · Experienced"}]};
  view.render(state);
  assert.deepEqual(select().children.map(option => [option.value, option.textContent]),
    [["home:simple", "Riverton Rovers · Simple"], ["away:experienced", "Forgeham United · Experienced"]]);
  assert.equal(controls().hidden, false);
  assert.deepEqual(view.selection(), {bucket_id: "away:experienced"});
  assert.equal(view.label(state), "Forgeham United · Experienced");
  const option = select().children[1];
  view.render({...state});
  assert.equal(select().children[1], option);
  view.connection(true);
  assert.equal(select().disabled, false);
  view.setBusy(true);
  assert.equal(select().disabled, true);
  view.connection(false);
  view.setBusy(false);
  assert.equal(select().disabled, true);
  // One bucket: nothing to switch to. None: the control is hidden.
  view.connection(true);
  view.render({audience: state.audience, audience_buckets: [state.audience_buckets[1]!]});
  assert.equal(select().disabled, true);
  view.render({audience: null, audience_buckets: []});
  assert.equal(controls().hidden, true);
  assert.equal(view.label({audience: null, audience_buckets: []}), null);
});

test("standard stat gains tracking controls and removes them after unpin", () => {
  const view = new MatchView(asDocument(documentStub()));
  const card: StatCard = { id: "all:shots", kind: "standard", label: "Shots", value: 2 };
  const original = fromElement(view.stat(card));
  assert.equal(original.querySelector("button"), null);
  const tracked = {...card, pinned: true, pin_id: "standard:all:shots"};
  const element = fromElement(view.stat(tracked, asElement(original)));
  let removed;
  view.onUnpin = id => { removed = id; };
  element.querySelector("button")!.listeners.click!();
  assert.equal(removed, "standard:all:shots");
  assert.equal(fromElement(view.stat({...tracked, value: 3}, asElement(element))), element);
  assert.equal(element.querySelector(".stat-value")!.textContent, "3");
  assert.equal(fromElement(view.stat(card, asElement(element))).querySelector("button"), null);
});

test("a default card shows both teams' values in one slot, home left, and updates in place", () => {
  const view = new MatchView(asDocument(documentStub()));
  const sides = [{ team_id: "riverton", name: "Riverton Rovers", value: 12 }, { team_id: "forgeham", name: "Forgeham United", value: null }];
  const card: StatCard = { id: "riverton:passes", kind: "standard", label: "Passes", value: 12, sides };
  const element = fromElement(view.stat(card));
  const value = element.querySelector(".stat-value")!;
  assert.deepEqual(value.children.map((side) => side.textContent), ["12", "—"]);
  assert.equal(value.title, "Riverton Rovers 12 · Forgeham United —");
  const again = fromElement(view.stat({ ...card, sides: [{ ...sides[0]!, value: 13 }, { ...sides[1]!, value: 9 }] }, asElement(element)));
  assert.equal(again, element);
  assert.deepEqual(element.querySelector(".stat-value")!.children.map((side) => side.textContent), ["13", "9"]);
});

test("club colours and crests come from the match data, never a club table", () => {
  const document = documentStub(),
    view = new MatchView(asDocument(document));
  view.teams = [{ id: "redcastle", branding: { primary_colour: "#ef0107", secondary_colour: "#063672", crest_asset_id: "redcastle" } }];
  view.render({
    match: {
      status: "live",
      teams: [
        { id: "redcastle", name: "Redcastle Town", code: "RCT", score: 1 },
        { id: "whitmore", name: "Whitmore Wanderers", branding: { primary_colour: "url(x)", crest_asset_id: "../evil" } },
      ],
      clock_seconds: 1200,
    },
    bucket_id: "neutral:casual", cards: [], events: [], narratives: [],
  });
  const home = document.getElementById("home-banner");
  assert.equal(home.dataset.club, "branded");
  assert.deepEqual(home.style.props, { "--club-primary": "#ef0107", "--club-secondary": "#063672" });
  assert.equal(document.getElementById("home-crest").src, "/assets/league/clubs/redcastle.svg");
  assert.equal(document.getElementById("home-mark").hidden, true);
  const away = document.getElementById("away-banner");
  assert.equal(away.dataset.club, "unknown");
  assert.deepEqual(away.style.props, {});
  assert.equal(document.getElementById("away-crest").hidden, true);
  assert.equal(document.getElementById("away-mark").textContent, "WHI");  // no code: the name's first letters
  // A missing crest file falls back to the monogram and stays that way.
  document.getElementById("home-crest").listeners.error!();
  view.render({ match: { status: "live", teams: [{ id: "redcastle", name: "Redcastle Town", code: "RCT" }] },
    cards: [], events: [], narratives: [] });
  assert.equal(document.getElementById("home-crest").hidden, true);
  assert.equal(document.getElementById("home-mark").hidden, false);
  assert.equal(document.getElementById("home-mark").textContent, "RCT");
});

test("once live only the connection line hides; the demo's Skip ahead and live-from note stay reachable", () => {
  const document = documentStub(), view = new MatchView(asDocument(document));
  view.connection("connecting");
  assert.equal(document.getElementById("connection-bar").hidden, false);
  view.connection("live");
  assert.equal(document.getElementById("connection-bar").hidden, true);
  assert.notEqual(document.getElementById("inside-the-game").hidden, true);
});

test("a scheduled match counts down to kickoff, then shows the live clock", () => {
  const document = documentStub(), view = new MatchView(asDocument(document));
  const kickoff = "2026-10-20T15:00:00.000Z", at = Date.parse(kickoff);
  const state = (match: object) => ({ match: { teams: [{ name: "Riverton Rovers" }, { name: "Forgeham United" }], ...match },
    cards: [], events: [], narratives: [] });
  view.render(state({ status: "scheduled", scheduled_kickoff: kickoff, clock_seconds: null }));
  assert.equal(document.getElementById("home-name").textContent, "Riverton Rovers");
  view.tick(at - 75_000);
  assert.equal(document.getElementById("match-clock").textContent, "KO in 1:15");
  view.tick(at + 1000);
  assert.equal(document.getElementById("match-clock").textContent, "KICK-OFF");
  view.render(state({ status: "live", clock_seconds: 4 }));
  view.tick(at + 9000);
  assert.equal(document.getElementById("match-clock").textContent, "0:04");
});

test("match snapshots do not render the developer event feed", () => {
  const document = documentStub(), view = new MatchView(asDocument(document));
  const get = document.getElementById;
  document.getElementById = (id) => {
    assert.ok(!["events", "event-title", "event-detail", "event-count"].includes(id));
    return get(id);
  };
  view.render({
    match: { status: "live", teams: [], clock_seconds: 120 },
    bucket_id: "neutral:casual", cards: [], narratives: [],
    events: [{ event_type: "shot", event_id: "one", match_time_seconds: 120 }],
  });
});

test("answer reveal runs on completion, not restored history or pin changes", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  const turn = { request_id: "request-one", prompt: "Shots?", status: "pending" };
  const container = document.getElementById("chat-messages");
  view.render({ turns: [turn] });
  assert.ok(container.querySelector(".answer-waiting"));
  const saved = { ...turn, id: "database-one" };
  const reply = { text: "Three shots.", offers: [] };
  view.render({ turns: [{ ...saved, reply }] });
  const answer = container.querySelector(".answer-reveal")!;
  assert.equal(answer.textContent, "Three shots.");
  view.render({ turns: [{ ...saved, reply }] });
  assert.equal(container.querySelector(".answer-reveal"), answer);
  view.render({ turns: [{ ...saved, reply: { ...reply, offers: [{ id: "pin", value: 3 }] } }] });
  assert.equal(container.querySelector(".answer-reveal"), null);
  const restored = new QuestionView(asDocument(documentStub()));
  restored.render({ turns: [{ ...saved, reply }] });
  assert.equal(fromElement(restored.get("chat-messages")).querySelector(".answer-reveal"), null);
});

test("failed answers stop loading and empty-state refresh preserves its DOM", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  const messages = () => fromElement(view.get("chat-messages"));
  view.render({ turns: [] });
  const empty = messages().children[0];
  view.render({ turns: [] });
  assert.equal(messages().children[0], empty);
  view.render({ turns: [{ id: "one", prompt: "Shots?", status: "failed" }] });
  assert.equal(messages().querySelector(".answer-waiting"), null);
});

test("Insights renders upstream narrative wording unchanged as text", () => {
  const view = new MatchView(asDocument(documentStub()));
  const text = "Five corners since the break give Riverton Rovers chances to threaten. <No rewrite>";
  const article = fromElement(view.narrative({ clock_seconds: 4260, text }));
  assert.equal(article.children[0]!.textContent, "71:00");
  assert.equal(article.children[1]!.textContent, text);
});

test("percentage offers retain ETL units in the chat card", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  view.render({turns: [{id: "percentage", prompt: "Riverton Rovers possession?", reply: {
    text: "Riverton Rovers possession: 35.9%.",
    offers: [{id: "offer", label: "Riverton Rovers possession", value: 35.9, unit: "%"}],
  }}]});
  assert.equal(document.getElementById("chat-messages").querySelector("strong")!.textContent, "35.9%");
});

const replayReply = (over: Partial<Replay> = {}): Replay => ({
  page: 0, page_size: 2, total_items: 3, seconds: 102, playlist: "/media/hls/m1/live.m3u8",
  derived: { first: { event_types: ["pass"], outcome: "failed" }, then: { event_types: ["touch"] },
    within_seconds: 3, then_team: "opponent" },
  refine_offer: "Narrow to the second half?",
  clips: [
    { start: 1300, end: 1310, captions: ["21′ Ashworth shot"], playlist_start: 1, playlist_end: 11 },
    { start: 1380, end: 1392, captions: ["23′ Ashworth header saved"], playlist_start: 14, playlist_end: 26 },
  ],
  ...over,
});
const texts = (element: Element): string[] =>
  [element.textContent, ...element.children.flatMap(texts)].filter(Boolean);

test("replay replies show a playable frame with length, derived definition and refine offer, not every event", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  const replay = replayReply();
  const played: unknown[] = [];
  view.onReplayPlay = (value, opener) => played.push(value, opener);
  const framed: unknown[] = [];
  view.onReplayFrame = (value, canvas) => framed.push(value, canvas);
  view.render({ turns: [{ id: 7, prompt: "Show Ashworth's chances", reply: {
    text: "Ashworth had two chances.", answer_kind: "replay", replay } }] });
  const card = document.getElementById("chat-messages").querySelector(".replay-card")!;
  const shown = texts(card);
  for (const expected of ["2 clips · 01:42", "Page 1 of 2",
    "Derived: failed pass, then opponent touch within 3 s", "Narrow to the second half?", "Show more"])
    assert.ok(shown.includes(expected), expected);
  assert.ok(!shown.some((text) => text?.includes("Ashworth")), "captions are not listed in chat");
  assert.equal(framed[0], replay);
  assert.equal(framed[1], card.querySelector(".replay-still"));
  assert.equal(card.querySelector(".replay-previous"), null);
  const play = card.querySelector(".replay-play")!;
  assert.equal(play.disabled, false);
  play.listeners.click!();
  assert.equal(played[0], replay);
  assert.equal(played[1], play);
});

test("Show more fetches the next page into the same card and paging back reuses the saved page", async () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  const calls: unknown[][] = [];
  const second = replayReply({ page: 1, clips: [
    { start: 2000, end: 2010, captions: ["33′ Goal"], playlist_start: 1, playlist_end: 11 }] });
  view.onReplayPage = async (...args) => { calls.push(args); return second; };
  const session = { turns: [{ id: 7, prompt: "Shots", reply: { text: "Shots.", replay: replayReply() } }] };
  view.render(session);
  const messages = document.getElementById("chat-messages");
  await messages.querySelector(".replay-more")!.listeners.click!();
  assert.deepEqual(calls, [[7, 1]]);
  let card = messages.querySelector(".replay-card")!;
  assert.ok(texts(card).includes("1 clip · 01:42"));
  assert.ok(texts(card).includes("Page 2 of 2"));
  assert.equal(card.querySelector(".replay-more"), null);
  assert.equal(card.focused, true);
  view.render(session); // unchanged turn keeps the paged card
  assert.equal(messages.querySelector(".replay-card"), card);
  await card.querySelector(".replay-previous")!.listeners.click!();
  card = messages.querySelector(".replay-card")!;
  assert.ok(texts(card).includes("2 clips · 01:42"));
  assert.equal(calls.length, 1);
});

test("a failed page load keeps the card and explains the retry", async () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  view.onReplayPage = async () => { throw new Error("offline"); };
  view.render({ turns: [{ id: 7, prompt: "Shots", reply: { text: "Shots.", replay: replayReply() } }] });
  const messages = document.getElementById("chat-messages");
  await messages.querySelector(".replay-more")!.listeners.click!();
  const card = messages.querySelector(".replay-card")!;
  assert.ok(texts(card).includes("Could not load those clips. Please try again."));
  assert.ok(texts(card).includes("2 clips · 01:42"));
});

test("restored replay turns without footage show a disabled frame and say why", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  view.render({ turns: [{ id: 3, prompt: "Goals", reply: { text: "One goal.", replay: replayReply({
    total_items: 1, playlist: null, derived: null, refine_offer: null,
    clips: [{ start: 10, end: 20, captions: ["12′ Goal"] }] }) } }] });
  const card = document.getElementById("chat-messages").querySelector(".replay-card")!;
  const play = card.querySelector(".replay-play")!;
  assert.equal(play.disabled, true);
  assert.equal(play["aria-label"], "Footage unavailable");
  assert.ok(texts(card).includes("Footage unavailable for these clips."));
  assert.equal(card.querySelector(".replay-more"), null);
});

const clarificationTurn = (id = "clarify") => ({ id, prompt: "Headers?", reply: {
  status: "clarification", text: "Which headers?", clarification: {
    question: "Which headers?", options: ["Headed shots", "Headed passes"], allow_free_text: true,
  },
} });

test("clarification replies offer accessible bounded choices without submitting until selected", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  const answers: string[] = [];
  view.onClarify = text => answers.push(text);
  view.render({ turns: [clarificationTurn()] });
  const card = document.getElementById("chat-messages").querySelector(".clarification")!;
  assert.equal(card.role, "group");
  assert.equal(card["aria-label"], "Which headers?");
  assert.deepEqual(answers, []);
  const options = card.querySelector(".clarification-options")!.children;
  assert.deepEqual(options.map(item => item.textContent), ["Headed shots", "Headed passes"]);
  assert.equal(options[0]!.type, "button");
  assert.equal(options[0]!.disabled, false);
  options[0]!.listeners.click!();
  options[0]!.listeners.click!();
  assert.deepEqual(answers, ["Headed shots"], "double click does not submit twice");
});

test("clarification free text focuses the normal composer and supports empty options", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  const turn = clarificationTurn();
  turn.reply.clarification.options = [];
  view.render({ turns: [turn] });
  document.getElementById("chat-messages").querySelector(".clarification-write")!.listeners.click!();
  assert.equal(document.getElementById("question-input").focused, true);
  turn.reply.clarification.allow_free_text = false;
  view.render({ turns: [turn] });
  assert.equal(document.getElementById("chat-messages").querySelector(".clarification-write"), null);
});

test("only latest unanswered clarification stays interactive; pending, takeover and reconnect are respected", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  const turn = clarificationTurn();
  const messages = document.getElementById("chat-messages");
  const option = () => messages.querySelector(".clarification-option")!;
  view.render({ turns: [turn] });
  view.status("This session ended. Reconnect to continue.", true);
  assert.equal(option().disabled, true);
  view.render({ turns: [turn] });
  assert.equal(option().disabled, true, "history refresh cannot unlock a disabled session");
  view.status("Answers grounded in live matches");
  assert.equal(option().disabled, false);
  view.render({ turns: [turn, { id: "answer", prompt: "Headed shots", status: "pending" }] });
  assert.equal(option().disabled, true);
  view.status("Ready");
  assert.equal(option().disabled, true);
  view.render({ turns: [turn, { id: "answer", prompt: "Headed shots", reply: { text: "Three." } }] });
  assert.equal(option().disabled, true);
  view.render({ turns: [turn, clarificationTurn("new")] });
  assert.equal(messages.children[0]!.querySelector(".clarification-option")!.disabled, true);
  assert.equal(messages.children[1]!.querySelector(".clarification-option")!.disabled, false);
});

test("clarification text is escaped and legacy free-text replies still render", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  const turn = clarificationTurn();
  turn.reply.clarification.options = ["<img src=x onerror=alert(1)>"];
  view.render({ turns: [turn] });
  const messages = document.getElementById("chat-messages");
  assert.equal(messages.querySelector(".clarification-option")!.textContent, turn.reply.clarification.options[0]);
  view.render({ turns: [{ id: "legacy", reply: { status: "clarification", text: "Which player?" } }] });
  assert.equal(messages.querySelector(".chat-answer")!.textContent, "Which player?");
  assert.equal(messages.querySelector(".clarification"), null);
});

test("composite offers and pinned cards preserve units and unavailable values", () => {
  const document = documentStub(), questions = new QuestionView(asDocument(document));
  const cards: StatCard[] = [
    { id: "percent", value: null, unit: "%" },
    { id: "distance", value: 12.4, unit: "m" },
    { id: "invalid", value: NaN, unit: "%" },
    { id: "zero", value: 0, unit: "%" },
  ];
  const view = new MatchView(asDocument(document));
  for (const [index, expected] of ["—", "12.4 m", "—", "0%"].entries()) {
    const card = cards[index]!;
    questions.render({ turns: [{ id: "offer", reply: { text: "Result", offers: [{ ...card, id: String(card.id) }] } }] });
    assert.equal(document.getElementById("chat-messages").querySelector("strong")!.textContent, expected);
    assert.equal(fromElement(view.stat(card)).querySelector(".stat-value")!.textContent, expected);
  }
});

test("answers carry a compact receipt; facts expand and new prices re-cost it without re-asking", () => {
  const document = documentStub(), view = new QuestionView(asDocument(document));
  view.prices = { input: 0.4, output: 1.6 };
  view.render({ turns: [{ id: 3, prompt: "Riverton Rovers shots?", reply: { text: "Riverton Rovers have 16 shots.",
    evidence: [{ id: "stat:riverton:shots", kind: "stat", label: "Riverton Rovers shots" }],
    usage: { input_tokens: 1450, output_tokens: 350, calls: 2, seconds: 4.2 } } }] });
  const line = document.getElementById("chat-messages").querySelector(".answer-receipt-line")!;
  assert.equal(line.textContent, "✓ 1 fact · 1.8k tok · 4.2s · $0.001");
  const facts = document.getElementById("chat-messages").querySelector(".answer-facts")!;
  assert.equal(facts.hidden, true);
  line.listeners.click!();
  assert.equal(facts.hidden, false);
  assert.ok(texts(facts).includes("Riverton Rovers shots"));
  view.setPrices({ input: 400, output: 1600 });
  assert.equal(line.textContent, "✓ 1 fact · 1.8k tok · 4.2s · $1.140");
});
