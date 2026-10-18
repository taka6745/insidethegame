import { node, keyedList } from "./dom.js";
import { clock, number } from "./format.js";

export class QuestionView {
  constructor(document) {
    this.document = document;
    this.onTrack = () => {};
  }
  get(id) {
    return this.document.getElementById(id);
  }
  status(text, busy = false) {
    this.get("question-status").textContent = text;
    this.get("question-send").disabled = busy;
    this.get("question-input").disabled = busy;
    for (const button of this.document.querySelectorAll("[data-prompt]"))
      button.disabled = busy;
  }
  render(session) {
    const container = this.get("chat-messages");
    const atBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight <
      70;
    const offers = new Map(
      (session.offers || []).map((offer) => [offer.id, offer]),
    );
    const turns = (session.turns || []).slice(-50).map((turn, index) => ({
      ...turn,
      key: turn.id || turn.request_id || index,
      offers: (turn.reply?.offers || []).map(
        (offer) => offers.get(offer.id) || offer,
      ),
    }));
    if (turns.length)
      keyedList(
        container,
        turns,
        (turn) => turn.key,
        (turn) => this.turn(turn),
      );
    else {
      const empty = node(this.document, "div", "", "question-empty");
      empty.append(
        node(this.document, "h3", "What are you seeing?"),
        node(
          this.document,
          "p",
          "Ask about the match, explore a stat, or make sense of a football rule.",
        ),
      );
      container.replaceChildren(empty);
    }
    if (atBottom) container.scrollTop = container.scrollHeight;
    this.get("question-suggestions").hidden = turns.length > 0;
    this.get("agent-mode").textContent =
      session.mode === "fixture"
        ? "FIXTURE AGENT · DEMONSTRATION ANSWERS"
        : "MICROSOFT AGENT FRAMEWORK";
  }
  turn(turn) {
    const article = node(this.document, "article", "", "chat-turn");
    article.append(node(this.document, "p", turn.prompt, "chat-prompt"));
    if (!turn.reply) {
      article.append(
        node(
          this.document,
          "p",
          turn.status === "failed"
            ? "That answer could not be completed. Please try again."
            : "Checking the match…",
          "chat-answer",
        ),
      );
      return article;
    }
    article.append(node(this.document, "p", turn.reply.text, "chat-answer"));
    const snapshot = turn.reply.snapshot;
    if (snapshot)
      article.append(
        node(
          this.document,
          "div",
          `As of ${snapshot.clock_seconds === null ? "before kickoff" : clock(snapshot.clock_seconds)} · answer snapshot`,
          "chat-meta",
        ),
      );
    if (turn.reply.evidence?.length)
      article.append(
        node(
          this.document,
          "div",
          turn.reply.evidence.map((evidence) => evidence.label).join(" · "),
          "chat-meta",
        ),
      );
    for (const offer of turn.offers) {
      const card = node(this.document, "div", "", "offer");
      card.append(
        node(this.document, "span", offer.label),
        node(this.document, "strong", number(offer.value)),
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
    return article;
  }
}
