import { node } from "./dom.ts";
import type { Clarification } from "./types.ts";

/** Suggested replies use the same conversation as a typed follow-up. */
export class ClarificationView {
  readonly element: HTMLElement;
  private readonly buttons: HTMLButtonElement[] = [];
  private enabled = false;

  constructor(document: Document, clarification: Clarification, answer: (text: string) => void,
    write: () => void) {
    this.element = node(document, "div", "", "clarification");
    this.element.setAttribute("role", "group");
    this.element.setAttribute("aria-label", clarification.question);
    this.element.append(node(document, "span", "Choose an answer", "clarification-label"));
    const choices = node(document, "div", "", "clarification-options");
    for (const option of clarification.options) {
      const button = node(document, "button", option, "clarification-option");
      button.type = "button";
      button.addEventListener("click", () => {
        if (!this.enabled) return;
        this.setEnabled(false);
        answer(option);
      });
      this.buttons.push(button);
      choices.append(button);
    }
    this.element.append(choices);
    if (clarification.allow_free_text) {
      const button = node(document, "button", "Type another answer", "clarification-write");
      button.type = "button";
      button.addEventListener("click", () => { if (this.enabled) write(); });
      this.buttons.push(button);
      this.element.append(button);
    }
    this.setEnabled(false);
  }

  setEnabled(enabled: boolean) {
    this.enabled = enabled;
    for (const button of this.buttons) button.disabled = !enabled;
  }
}
