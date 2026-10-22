import test from "node:test";
import assert from "node:assert/strict";
import { MatchPicker, sides } from "../match/picker.ts";
import { validMatchId } from "../match/api.ts";
import { stub } from "./support.ts";

class Node {
  [key: string]: unknown;
  children: Node[] = [];
  dataset: Record<string, string> = {};
  textContent = "";
  className = "";
  hidden = false;
  tag: string;
  constructor(tag: string) { this.tag = tag; }
  append(...children: Node[]) { this.children.push(...children); }
  replaceChildren(...children: Node[]) { this.children = children; }
  insertBefore(child: Node, before: Node | null) {
    this.children = this.children.filter((c) => c !== child);
    this.children.splice(before ? this.children.indexOf(before) : this.children.length, 0, child);
  }
  remove() {}
  addEventListener() {}
  setAttribute(name: string, value: string) { this[name] = value; }
  get text(): string { return [this.textContent, ...this.children.map((c) => c.text)].join(" ").trim(); }
}
function picker() {
  const nodes = new Map<string, Node>();
  const doc = {
    createElement: (tag: string) => new Node(tag),
    getElementById: (id: string) => nodes.get(id) ?? nodes.set(id, new Node("div")).get(id),
  };
  return { view: new MatchPicker(stub<Document>(doc)), nodes };
}

test("the picker links each listed match by id with status, score and clock", () => {
  const { view, nodes } = picker();
  view.render([
    { match_id: "chelsea-united-1a2b3c4d", status: "live", clock_seconds: 431,
      teams: [{ id: "manutd", position: "away", name: "Manchester United", score: 0, branding: { crest_asset_id: "manutd" } },
        { id: "chelsea", position: "home", name: "Chelsea", score: 1, branding: { crest_asset_id: "chelsea", primary_colour: "#001c68" } }] },
    { match_id: "Bad/Id", status: "live", teams: [] },
    { match_id: "arsenal-spurs-0f0f0f0f", status: "finished", teams: [{ name: "Arsenal" }, { name: "Spurs" }] },
  ]);
  const rows = nodes.get("match-list")!.children;
  assert.equal(rows.length, 2);
  const link = rows[0]!.children[0]!;
  assert.equal(link.href, "/?match=chelsea-united-1a2b3c4d");
  assert.equal(link.dataset.status, "live");
  assert.match(link.text, /^Chelsea 1 – 0 Live · 7:11 Manchester United$/);
  assert.equal(link.children[0]!.children[0]!.src, "/assets/league/clubs/chelsea.svg");
  assert.match(rows[1]!.text, /v Full time/);
});

test("an empty list says when matches appear; ids outside the slug shape never reach a URL", () => {
  const { view, nodes } = picker();
  view.render([]);
  assert.match(nodes.get("match-list")!.text, /about a minute before kick-off/);
  assert.ok(validMatchId("chelsea-united-1a2b3c4d"));
  for (const bad of ["", "../x", "A", "a b", "x".repeat(65), null]) assert.equal(validMatchId(bad), false);
  assert.deepEqual(sides([{ position: "away", name: "B" }, { position: "home", name: "A" }]).map((t) => t.name), ["A", "B"]);
});
