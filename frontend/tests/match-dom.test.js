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
  assert.equal(turn.children[2].children[0].textContent, unsafe);
  assert.equal(turn.querySelector(".answer-time").textContent, "1′");
  assert.equal(turn.querySelector(".answer-time")["aria-label"], "Answer as of 1:40");
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
});

test("match snapshots do not render the developer event feed", () => {
  const document = documentStub(), view = new MatchView(document);
  const get = document.getElementById;
  document.getElementById = (id) => {
    assert.ok(!["events", "event-title", "event-detail", "event-count"].includes(id));
    return get(id);
  };
  view.render({
    match: { status: "running", position: 1, total: 35, teams: [], clock_seconds: 120 },
    bucket: "neutral:casual", cards: [], narratives: [],
    events: [{ event_type: "shot", event_id: "one", match_time_seconds: 120 }],
  });
});

test("answer reveal runs on completion, not restored history or pin changes", () => {
  const document = documentStub(), view = new QuestionView(document);
  const turn = { request_id: "request-one", prompt: "Shots?", status: "pending" };
  const container = document.getElementById("chat-messages");
  view.render({ turns: [turn] });
  assert.ok(container.querySelector(".answer-waiting"));
  const saved = { ...turn, id: "database-one" };
  const reply = { text: "Three shots.", offers: [] };
  view.render({ turns: [{ ...saved, reply }] });
  const answer = container.querySelector(".answer-reveal");
  assert.equal(answer.textContent, "Three shots.");
  view.render({ turns: [{ ...saved, reply }] });
  assert.equal(container.querySelector(".answer-reveal"), answer);
  view.render({ turns: [{ ...saved, reply: { ...reply, offers: [{ id: "pin", value: 3 }] } }] });
  assert.equal(container.querySelector(".answer-reveal"), null);
  const restored = new QuestionView(documentStub());
  restored.render({ turns: [{ ...saved, reply }] });
  assert.equal(restored.get("chat-messages").querySelector(".answer-reveal"), null);
});

test("failed answers stop loading and empty-state refresh preserves its DOM", () => {
  const document = documentStub(), view = new QuestionView(document);
  view.render({ turns: [] });
  const empty = view.get("chat-messages").children[0];
  view.render({ turns: [] });
  assert.equal(view.get("chat-messages").children[0], empty);
  view.render({ turns: [{ id: "one", prompt: "Shots?", status: "failed" }] });
  assert.equal(view.get("chat-messages").querySelector(".answer-waiting"), null);
});

test("Insights renders upstream narrative wording unchanged as text", () => {
  const view = new MatchView(documentStub());
  const text = "Five corners since the break give Chelsea chances to threaten. <No rewrite>";
  const article = view.narrative({ clock_seconds: 4260, text });
  assert.equal(article.children[0].textContent, "71:00");
  assert.equal(article.children[1].textContent, text);
});
