import { node } from "./dom.ts";
import { ClarificationView } from "./clarification-view.ts";
import { CROSS_MATCH, markOtherMatch } from "./other-match.ts";
import type { FollowOption, FollowTurn } from "./types.ts";

/** "Arsenal v Liverpool": the other match a cross-match option is in. */
function matchName(option: FollowOption): string {
  return (option.other_match?.teams || []).map((team) => team.short_name || team.name).join(" v ");
}

/** The follow chat in the Insights tab: suggestion chips, planner turns and the composer. Text only. */
export class FollowView {
  document: Document;
  onFollow: (option: FollowOption) => unknown = () => {};
  onUnfollow: () => unknown = () => {};
  onWrite: () => unknown = () => {};
  private enabled = false;
  private latest?: string;
  private clarification?: ClarificationView;
  constructor(document: Document) {
    this.document = document;
  }
  get(id: string): HTMLElement {
    return this.document.getElementById(id) as HTMLElement;
  }
  status(text: string, locked: boolean) {
    this.get("follow-status").textContent = text;
    (this.get("follow-input") as HTMLInputElement).disabled = locked;
    (this.get("follow-send") as HTMLButtonElement).disabled = locked;
  }
  /** Chips and the newest turn's buttons; off while a follow change or chat turn runs. */
  actions(enabled: boolean) {
    this.enabled = enabled;
    for (const button of this.get("follow-suggestions").querySelectorAll<HTMLButtonElement>("button"))
      button.disabled = !enabled;
    for (const button of this.get("follow-messages").querySelectorAll<HTMLButtonElement>(".follow-action"))
      button.disabled = !enabled || button.dataset.turn !== this.latest;
    this.clarification?.setEnabled(enabled);
  }
  suggestions(items: FollowOption[]) {
    const container = this.get("follow-suggestions");
    container.replaceChildren(...items.map((item) => {
      const chip = node(this.document, "button", item.label, `follow-chip${item.other_match ? ` ${CROSS_MATCH}` : ""}`);
      chip.type = "button";
      chip.setAttribute("aria-label", `Follow ${item.label}${item.other_match ? ` in ${matchName(item)}` : ""}`);
      chip.disabled = !this.enabled;
      chip.addEventListener("click", () => this.onFollow(item));
      return chip;
    }));
    container.hidden = !items.length;
  }
  render(turns: FollowTurn[]) {
    const container = this.get("follow-messages");
    // The newest few: the feed below stays the focus.
    const shown = turns.slice(-3);
    const last = shown.at(-1);
    this.latest = last && last.status !== "pending" ? String(last.request_id || last.id) : undefined;
    this.clarification = undefined;
    // Re-rendered whole: the newest turn decides which buttons are live.
    container.replaceChildren(...shown.map((turn, index) => this.turn(turn, index === shown.length - 1)));
    container.hidden = !shown.length;
    container.scrollTop = container.scrollHeight;
    this.actions(this.enabled);
  }
  private turn(turn: FollowTurn, newest: boolean): HTMLElement {
    const key = String(turn.request_id || turn.id);
    const article = node(this.document, "article", "", "follow-turn");
    article.append(node(this.document, "p", turn.prompt, "chat-prompt"));
    const reply = turn.reply;
    if (!reply) {
      const waiting = turn.status === "pending";
      article.append(node(this.document, "p",
        waiting ? "Finding that story…" : "That could not be completed. Please try again.",
        waiting ? "chat-answer answer-waiting" : "chat-answer"));
      return article;
    }
    article.append(node(this.document, "p", reply.text, "chat-answer"));
    const candidates = reply.candidates || [];
    if (reply.status === "proposal" && reply.proposal) {
      const option = reply.proposal;
      const card = node(this.document, "div", "", "follow-proposal");
      card.append(node(this.document, "span", option.label, "follow-proposal-label"));
      card.append(this.action(key, "Follow", `Follow ${option.label}`, () => this.onFollow(option)));
      article.append(markOtherMatch(this.document, card, option.other_match));
    } else if (reply.status === "clarify" && candidates.length && newest) {
      // Only the newest open question is answerable; picking a candidate follows it.
      this.clarification = new ClarificationView(this.document,
        { question: reply.text, options: candidates.map((c) => c.label), allow_free_text: true },
        (label) => {
          const chosen = candidates.find((c) => c.label === label);
          if (chosen) this.onFollow(chosen);
        }, () => this.onWrite());
      article.append(this.clarification.element);
    } else if (reply.status === "unfollow") {
      article.append(this.action(key, "Stop following", "Stop following", () => this.onUnfollow()));
    }
    return article;
  }
  private action(turn: string, text: string, label: string, run: () => unknown) {
    const button = node(this.document, "button", text, "follow-action");
    button.type = "button";
    button.dataset.turn = turn;
    button.setAttribute("aria-label", label);
    button.addEventListener("click", () => run());
    return button;
  }
}
