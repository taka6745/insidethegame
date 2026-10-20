import { node } from "./dom.ts";
import type { Audience, Snapshot } from "./types.ts";

/** Audience choice changes the current viewer, not their demo account identity. */
export class AudienceView {
  document: Document;
  team: HTMLSelectElement;
  style: HTMLSelectElement;
  live: boolean;
  busy: boolean;
  choicesKey?: string;
  constructor(document: Document) {
    this.document = document;
    this.team = document.getElementById("audience-team") as HTMLSelectElement;
    this.style = document.getElementById("audience-style") as HTMLSelectElement;
    this.live = false;
    this.busy = false;
  }
  selection(): Audience {
    return { team: this.team.value, fan_style: this.style.value };
  }
  connection(live: boolean) {
    this.live = live;
    this.setBusy(this.busy);
  }
  setBusy(busy: boolean) {
    this.busy = busy;
    this.team.disabled = this.style.disabled = busy || !this.live;
  }
  render(snapshot: Pick<Snapshot, "match" | "audience">) {
    const teams = snapshot.match.teams || [];
    const choices = [
      ["home", teams[0]?.name || "Home team"],
      ["away", teams[1]?.name || "Away team"],
      ["neutral", "Neither"],
    ] as const;
    const key = JSON.stringify(choices);
    if (key !== this.choicesKey) {
      this.team.replaceChildren(...choices.map(([value, label]) => {
        const option = node(this.document, "option", label);
        option.value = value;
        return option;
      }));
      this.choicesKey = key;
    }
    if (snapshot.audience) {
      this.team.value = snapshot.audience.team;
      this.style.value = snapshot.audience.fan_style;
    }
  }
}
