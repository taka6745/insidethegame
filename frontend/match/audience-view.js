import { node } from "./dom.js";

/** Audience choice changes the current viewer, not their demo account identity. */
export class AudienceView {
  constructor(document) {
    this.document = document;
    this.team = document.getElementById("audience-team");
    this.style = document.getElementById("audience-style");
    this.live = false;
    this.busy = false;
  }
  selection() {
    return { team: this.team.value, fan_style: this.style.value };
  }
  connection(live) {
    this.live = live;
    this.setBusy(this.busy);
  }
  setBusy(busy) {
    this.busy = busy;
    this.team.disabled = this.style.disabled = busy || !this.live;
  }
  render(snapshot) {
    const teams = snapshot.match.teams || [];
    const choices = [
      ["home", teams[0]?.name || "Home team"],
      ["away", teams[1]?.name || "Away team"],
      ["neutral", "Neither"],
    ];
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
