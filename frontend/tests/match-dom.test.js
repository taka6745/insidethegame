import test from "node:test";
import assert from "node:assert/strict";
import { keyedList } from "../match/dom.js";
import { QuestionView } from "../match/chat-view.js";
import { MatchView } from "../match/view.js";

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.textContent = "";
    this.scrollTop = 20;
    this.scrollHeight = 1000;
    this.clientHeight = 300;
    this.listeners = {};
  }
  append(...children) {
    for (const child of children) this.insertBefore(child, null);
  }
  prepend(child) {
    this.insertBefore(child, this.children[0] || null);
  }
  insertBefore(child, before) {
    child.remove();
    const index = before ? this.children.indexOf(before) : this.children.length;
    this.children.splice(index, 0, child);
    child.parent = this;
  }
  replaceChildren(...children) {
    for (const child of [...this.children]) child.remove();
    this.append(...children);
  }
  replaceWith(other) {
    this.parent.insertBefore(other, this);
    this.remove();
  }
  remove() {
    if (this.parent) {
      this.parent.children.splice(this.parent.children.indexOf(this), 1);
      this.parent = null;
    }
  }
  addEventListener(name, fn) {
    this.listeners[name] = fn;
  }
  removeAttribute(name) {
    delete this[name];
  }
  setAttribute(name, value) {
    this[name] = value;
  }
  querySelector(selector) {
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
  set innerHTML(value) {
    throw new Error("Unsafe HTML assignment");
  }
}
function documentStub() {
  const nodes = new Map();
  return {
    body: new Element("body"),
    createElement: (tag) => new Element(tag),
    getElementById: (id) => {
      if (!nodes.has(id)) nodes.set(id, new Element("div"));
      return nodes.get(id);
    },
    querySelectorAll: () => [],
  };
}
test("unchanged keyed feed entries retain DOM identity and preserve user scroll", () => {
  const container = new Element("div"),
    render = (row) =>
      Object.assign(new Element("article"), { textContent: row.text });
  keyedList(
    container,
    [
      { id: "one", text: "First" },
      { id: "two", text: "Second" },
    ],
    (row) => row.id,
    render,
  );
  const original = container.children[0];
  keyedList(
    container,
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
    view = new QuestionView(document),
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
    turn = messages.children[0];
  assert.equal(turn.children[0].textContent, unsafe);
  assert.equal(turn.children[1].textContent, unsafe);
  assert.equal(turn.children[3].children[0].textContent, unsafe);
  assert.equal(messages.scrollTop, 20);
});
test("question history is capped at fifty turns and unchanged Track button retains identity", () => {
  const document = documentStub(),
    view = new QuestionView(document);
  const session = {
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
    view = new MatchView(document),
    container = new Element("section");
  const card = {
    id: "custom-rule",
    kind: "custom",
    label: "Headed shots",
    value: 1,
  };
  keyedList(
    container,
    [card],
    (row) => row.id,
    (row, existing) => view.stat(row, existing),
  );
  const button = container.children[0].querySelector("button");
  document.activeElement = button;
  keyedList(
    container,
    [{ ...card, value: 2 }],
    (row) => row.id,
    (row, existing) => view.stat(row, existing),
  );
  assert.equal(
    container.children[0].querySelector("button"),
    document.activeElement,
  );
  assert.equal(
    container.children[0].querySelector(".stat-value").textContent,
    "2",
  );
});

test("match view presents resumable replay controls for a restored partial run", () => {
  const document = documentStub(),
    view = new MatchView(document);
  view.render({
    match: {
      status: "ready",
      position: 10,
      total: 35,
      teams: [],
      clock_seconds: 1200,
    },
    bucket: "neutral:casual",
    cards: [],
    events: [],
    narratives: [],
  });
  assert.equal(document.getElementById("start-demo").hidden, false);
  assert.equal(
    document.getElementById("start-demo-label").textContent,
    "Resume match",
  );
  assert.equal(
    document.getElementById("demo-progress").textContent,
    "Ready to resume",
  );
});

test("event feed prefers roster display names and safely falls back for unknown identities", () => {
  const document = documentStub(),
    view = new MatchView(document);
  const event = {
    event_id: "shot",
    event_type: "shot",
    match_time_seconds: 100,
    team_id: "manutd",
    player_id: "bruno",
    player_name: "Bruno Fernandes",
    team_name: "Manchester United",
  };
  const named = view.event(event);
  assert.equal(named.children[2].textContent, "Shot · Bruno Fernandes");
  assert.equal(named.children[3].textContent, "Manchester United");
  const unknown = view.event({ ...event, player_name: null, team_name: null });
  assert.equal(unknown.children[2].textContent, "Shot · Bruno");
  assert.equal(unknown.children[3].textContent, "Manutd");
  const unsafe = view.event({
    ...event,
    player_name: "<img src=x onerror=alert(1)>",
  });
  assert.equal(
    unsafe.children[2].textContent,
    "Shot · <img src=x onerror=alert(1)>",
  );
});
