import { node } from "../shared/dom.ts";
import { statValue } from "./format.ts";
import type { StatCard } from "./types.ts";

/** Values keep their team labels in both answer offers and pinned cards. */
export function statDisplay(document: Document, card: Pick<StatCard, "value" | "unit" | "sides">): HTMLElement {
  if (!card.sides?.length) return node(document, "strong", statValue(card), "stat-value");
  const value = node(document, "div", "", "stat-value sides");
  value.title = card.sides.map(side => `${side.name || side.team_id} ${statValue({ ...card, value: side.value })}`).join(" · ");
  for (const side of card.sides) {
    const row = node(document, "span", "", "stat-side");
    const name = node(document, "span", side.name || side.team_id, "stat-team");
    name.title = side.name || side.team_id;
    row.append(name, node(document, "strong", statValue({ ...card, value: side.value }), "stat-number"));
    value.append(row);
  }
  return value;
}
