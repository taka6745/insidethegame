import { node, keyedList } from "../shared/dom.ts";
import { statDisplay } from "./stat-value.ts";
import { clock } from "./format.ts";
import { ClarificationView } from "./clarification-view.ts";
import { markOtherMatch } from "./other-match.ts";
import { replayCard } from "./replay-card.ts";
import { answerFacts, cachedPrices, receipt } from "./receipt.ts";
import type { Prices } from "./receipt.ts";
import type { ChatSession, ChatTurn, FollowOffer, Offer, Replay, Usage } from "./types.ts";

/** Enter sends the question; Shift+Enter adds a line and an IME composition keeps typing. */
export function sendsOnEnter(event: Pick<KeyboardEvent, "key" | "shiftKey" | "isComposing">): boolean {
  return event.key === "Enter" && !event.shiftKey && !event.isComposing;
}

type RenderedTurn = ChatTurn & { key: string | number; offers: Offer[]; clarificationActive: boolean };

export class QuestionView {
  document: Document;
  onTrack: (id: string) => unknown;
  onClarify?: (text: string) => unknown;
  private busy = false;
  private hasTurns = false;
  private clarifications = new Map<string, { view: ClarificationView; active: boolean }>();
  onReplayPage: (turnId: string | number, page: number) => Promise<Replay>;
  onReplayPlay: (replay: Replay, opener: HTMLElement) => unknown;
  onReplayFrame: (replay: Replay, canvas: HTMLCanvasElement) => unknown;
  /** "Follow this story?" accepted: open the follow view set up from the question (never follows by itself). */
  onFollowOffer: (offer: FollowOffer) => unknown = () => {};
  /** Turns whose follow offer the viewer turned down. */
  private declined = new Set<string>();
  /** Page currently shown in each turn's replay card; restored turns start at their saved page. */
  replayPages: Map<string, Replay>;
  /** Match clock the viewer was watching when each request was asked. */
  askedAt = new Map<string, number>();
  prices: Prices | null = cachedPrices();
  private receipts = new Set<{ element: HTMLElement; facts: number; usage: Usage }>();
  constructor(document: Document) {
    this.document = document;
    this.onTrack = () => {};
    this.onReplayPage = () => Promise.reject(new Error("Replay paging unavailable"));
    this.onReplayPlay = () => {};
    this.onReplayFrame = () => {};
    this.replayPages = new Map();
  }
  get(id: string): HTMLElement {
    return this.document.getElementById(id) as HTMLElement;
  }
  /** Drop cached replay pages (after a skip they describe the match before it). */
  forget() {
    this.replayPages.clear();
  }
  reset() {
    this.forget();
    this.askedAt.clear();
    this.declined.clear();
    this.clarifications.clear();
    this.receipts.clear();
  }
  status(text: string, busy = false) {
    this.busy = busy;
    this.updateClear();
    this.updateClarifications();
    this.get("question-status").textContent = text;
    (this.get("question-send") as HTMLButtonElement).disabled = busy;
    (this.get("question-input") as HTMLInputElement).disabled = busy;
    for (const button of this.document.querySelectorAll<HTMLButtonElement>("[data-prompt]"))
      button.disabled = busy;
  }
  render(session: ChatSession) {
    this.hasTurns = Boolean(session.turns?.length);
    this.updateClear();
    const container = this.get("chat-messages");
    const atBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight <
      70;
    const offers = new Map(
      (session.offers || []).map((offer) => [offer.id, offer]),
    );
    const turns = (session.turns || []).slice(-50).map((turn, index): RenderedTurn => ({
      ...turn,
      key: turn.request_id || turn.id || index,
      clarificationActive: index === Math.min((session.turns || []).length, 50) - 1
        && turn.reply?.status === "clarification"
        && !(session.turns || []).some(item => item.status === "pending"),
      offers: (turn.reply?.offers || []).map(
        (offer) => offers.get(offer.id) || offer,
      ),
    }));
    if (turns.length)
      keyedList(
        container,
        turns,
        (turn) => turn.key,
        (turn, previous) =>
          this.turn(turn, Boolean(previous?.querySelector(".answer-waiting"))),
      );
    else if (!container.querySelector(".question-empty")) {
      const empty = node(this.document, "div", "", "question-empty");
      empty.append(
        node(this.document, "h3", "What are you seeing?"),
        node(
          this.document,
          "p",
          "Ask a question. Track a stat.",
        ),
      );
      container.replaceChildren(empty);
    }
    const keys = new Set(turns.filter(turn => turn.reply?.clarification).map(turn => String(turn.key)));
    for (const key of this.clarifications.keys()) if (!keys.has(key)) this.clarifications.delete(key);
    this.updateClarifications();
    if (atBottom) container.scrollTop = container.scrollHeight;
    this.get("question-suggestions").hidden = turns.length > 0;
    this.get("agent-mode").textContent =
      session.mode === "unavailable" ? "No model configured" : "";
  }
  /** part: one match's answer within a several-match answer (no prompt of its own). */
  turn(turn: RenderedTurn, reveal = false, part = false): HTMLElement {
    const article = node(this.document, "article", "", part ? "chat-turn chat-part" : "chat-turn");
    if (!part) article.append(node(this.document, "p", turn.prompt, "chat-prompt"));
    if (!turn.reply) {
      const waiting = turn.status !== "failed";
      const answer = node(
        this.document,
        "p",
        waiting
          ? "Checking the match…"
          : "That answer could not be completed. Please try again.",
        waiting ? "chat-answer answer-waiting" : "chat-answer",
      );
      if (waiting) {
        const dots = node(this.document, "span", "", "answer-dots");
        dots.setAttribute("aria-hidden", "true");
        for (let index = 0; index < 3; index++)
          dots.append(node(this.document, "span"));
        answer.append(dots);
      }
      article.append(answer);
      return article;
    }
    const answer = node(
      this.document, "p", turn.reply.text,
      reveal ? "chat-answer answer-reveal" : "chat-answer",
    );
    const snapshot = turn.reply.snapshot;
    if (snapshot) {
      const seconds = snapshot.clock_seconds;
      const beforeKickoff = seconds === null || seconds === undefined;
      const timestamp = node(this.document, "span",
        beforeKickoff ? "Pre-match" : `${Math.floor(Math.max(0, seconds) / 60)}′`,
        "answer-time");
      // Data can trail the picture: name the exact clock when it is well behind what was watched.
      const watched = this.askedAt.get(String(turn.request_id));
      const behind = !beforeKickoff && watched !== undefined && watched - seconds > 10;
      if (behind) timestamp.textContent = `as of ${clock(seconds)}`;
      const description = `Answer as of ${beforeKickoff ? "before kickoff" : clock(seconds)}`;
      timestamp.title = description;
      timestamp.setAttribute("aria-label", description);
      answer.className += " timestamped";
      answer.append(timestamp);
    }
    article.append(answer);
    if (turn.reply.usage) article.append(this.receipt(answerFacts(turn.reply), turn.reply.usage));
    if (turn.reply.status === "clarification" && turn.reply.clarification) {
      const clarification = new ClarificationView(this.document, turn.reply.clarification,
        text => this.onClarify?.(text), () => this.get("question-input").focus());
      this.clarifications.set(String(turn.key), { view: clarification, active: turn.clarificationActive });
      article.append(clarification.element);
    }
    for (const offer of turn.offers) {
      const card = node(this.document, "div", "", "offer");
      card.append(
        node(this.document, "span", offer.label),
        statDisplay(this.document, offer),
      );
      const button = node(
        this.document,
        "button",
        offer.calculation_id
          ? "Tracking in your match stats ✓"
          : "Track this stat",
      );
      const icon = this.document.createElement("img");
      icon.src = "/assets/icons/track.svg";
      icon.alt = "";
      button.prepend(icon);
      button.disabled = Boolean(offer.calculation_id);
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await this.onTrack(offer.id);
        } finally {
          if (button.isConnected && !offer.calculation_id)
            button.disabled = false;
        }
      });
      card.append(button);
      article.append(card);
    }
    if (turn.reply.replay) article.append(this.replay(turn, turn.reply.replay));
    (turn.reply.parts ?? []).forEach((part, index) => {  // one answer per match, marked like any other match's
      article.append(this.turn({ key: `${turn.key}:${index}`, reply: part, offers: part.offers ?? [],
        clarificationActive: false }, reveal, true));
    });
    const offer = turn.reply.follow_offer;
    if (offer && !this.declined.has(String(turn.key))) article.append(this.followOffer(String(turn.key), offer));
    return markOtherMatch(this.document, article, turn.reply.other_match);
  }
  /** One offer per answer: Follow opens the follow view prefilled; No thanks removes it. */
  private followOffer(key: string, offer: FollowOffer): HTMLElement {
    const card = node(this.document, "div", "", "follow-offer");
    card.append(node(this.document, "span", "Follow this story?", "follow-offer-text"));
    const follow = node(this.document, "button", "Follow", "follow-offer-yes");
    follow.type = "button";
    follow.addEventListener("click", () => this.onFollowOffer(offer));
    const decline = node(this.document, "button", "No thanks", "follow-offer-no");
    decline.type = "button";
    decline.addEventListener("click", () => {
      this.declined.add(key);
      card.remove();
    });
    card.append(follow, decline);
    return card;
  }
  private updateClear() {
    const button = this.get("question-clear") as HTMLButtonElement | null;
    if (button) button.disabled = this.busy || !this.hasTurns;
  }
  private updateClarifications() {
    for (const { view, active } of this.clarifications.values()) view.setEnabled(active && !this.busy);
  }
  replay(turn: RenderedTurn, saved: Replay, status = ""): HTMLElement {
    const key = String(turn.key);
    const card: HTMLElement = replayCard(this.document, this.replayPages.get(key) || saved, {
      refineOffer: turn.reply?.refine_offer,
      status,
      play: (replay, opener) => this.onReplayPlay(replay, opener),
      frame: (replay, canvas) => this.onReplayFrame(replay, canvas),
      page: async (page) => {
        let next = "";
        try {
          if (turn.id === undefined) throw new Error("Replay is not saved yet");
          this.replayPages.set(key, page === saved.page ? saved : await this.onReplayPage(turn.id, page));
        } catch {
          next = "Could not load those clips. Please try again.";
        }
        if (!card.isConnected) return;
        const fresh = this.replay(turn, saved, next);
        card.replaceWith(fresh);
        fresh.tabIndex = -1;
        fresh.focus?.();
      },
    });
    return card;
  }
  /** Compact answer receipt; tapping the facts lists what the answer stood on. */
  receipt(facts: string[], usage: Usage): HTMLElement {
    const wrapper = node(this.document, "div", "", "answer-receipt");
    const summary = node(this.document, facts.length ? "button" : "span", "", "answer-receipt-line");
    const entry = { element: summary, facts: facts.length, usage };
    this.receipts.add(entry);
    this.describeReceipt(entry);
    wrapper.append(summary);
    if (facts.length) {
      const list = node(this.document, "ul", "", "answer-facts");
      list.hidden = true;
      for (const fact of facts) list.append(node(this.document, "li", fact));
      summary.setAttribute("aria-expanded", "false");
      summary.addEventListener("click", () => {
        list.hidden = !list.hidden;
        summary.setAttribute("aria-expanded", String(!list.hidden));
      });
      wrapper.append(list);
    }
    return wrapper;
  }
  describeReceipt(entry: { element: HTMLElement; facts: number; usage: Usage }) {
    const { line, detail } = receipt(entry.facts, entry.usage, this.prices);
    entry.element.textContent = line;
    entry.element.title = detail;
    entry.element.setAttribute("aria-label", `${line}. ${detail}`);
  }
  /** New prices re-cost every visible receipt; nothing is re-asked. */
  setPrices(prices: Prices) {
    this.prices = prices;
    for (const entry of this.receipts)
      if (entry.element.isConnected) this.describeReceipt(entry);
      else this.receipts.delete(entry);
  }
}
