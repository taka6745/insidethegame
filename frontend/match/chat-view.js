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
      key: turn.request_id || turn.id || index,
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
    if (atBottom) container.scrollTop = container.scrollHeight;
    this.get("question-suggestions").hidden = turns.length > 0;
    this.get("agent-mode").textContent =
      session.mode === "fixture"
        ? "Demo answers"
        : "";
  }
  turn(turn, reveal = false) {
    const article = node(this.document, "article", "", "chat-turn");
    article.append(node(this.document, "p", turn.prompt, "chat-prompt"));
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
      const description = `Answer as of ${beforeKickoff ? "before kickoff" : clock(seconds)}`;
      timestamp.title = description;
      timestamp.setAttribute("aria-label", description);
      answer.className += " timestamped";
      answer.append(timestamp);
    }
    article.append(answer);
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
