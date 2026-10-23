import { node } from "../shared/dom.ts";
import { ConflictError } from "./api.ts";
import type { DemoProfile, DevApi, ProfilesDocument } from "./api.ts";

/** An editor row: selections as text, `layer=option, layer=option`. */
export interface ProfileDraft { id: string; display_name: string; selections: string }

const FIELDS = ["id", "display_name", "selections"] as const;
// Narrow screens hide the column headings; empty fields still say what they hold.
const PLACEHOLDERS = { id: "id", display_name: "Name", selections: "layer=option, layer=option" };
const MAX = { id: 64, display_name: 80, selections: 400 };
const PROFILE_ID = /^[a-z0-9][a-z0-9-]{0,63}$/;
const OPTION_ID = /^[a-z0-9][a-z0-9_-]{0,63}$/;

/** `side=home, depth=simple` → {side: "home", depth: "simple"}, or null if malformed. */
export function parseSelections(text: string): Record<string, string> | null {
  const selections: Record<string, string> = {};
  for (const pair of text.split(",").map((p) => p.trim()).filter(Boolean)) {
    const [layer, option, ...rest] = pair.split("=").map((p) => p.trim());
    if (rest.length || !layer || !option || !OPTION_ID.test(layer) || !OPTION_ID.test(option) || layer in selections) return null;
    selections[layer] = option;
  }
  return Object.keys(selections).length > 8 ? null : selections;
}

export function formatSelections(selections: Record<string, string>) {
  return Object.entries(selections).map(([layer, option]) => `${layer}=${option}`).join(", ");
}

const toDraft = (p: DemoProfile): ProfileDraft => ({ id: p.id, display_name: p.display_name, selections: formatSelections(p.selections) });
const toProfile = (d: ProfileDraft): DemoProfile => ({ id: d.id, display_name: d.display_name, selections: parseSelections(d.selections) ?? {} });

/** Why the profiles cannot be saved, or "" (the backend validates again against the default template). */
export function profilesIssue(profiles: ProfileDraft[]): string {
  if (!profiles.length) return "Keep at least one profile.";
  if (profiles.length > 50) return "At most 50 profiles.";
  const ids = new Set<string>();
  for (const [index, profile] of profiles.entries()) {
    const row = `Row ${index + 1}`;
    if (!PROFILE_ID.test(profile.id)) return `${row}: id must be lowercase letters, digits or -.`;
    if (ids.has(profile.id)) return `${row}: id "${profile.id}" is used twice.`;
    ids.add(profile.id);
    if (!profile.display_name.trim() || profile.display_name.length > 80) return `${row}: name must be 1–80 characters.`;
    if (parseSelections(profile.selections) === null) return `${row}: selections must be layer=option pairs (option ids), e.g. layer=option.`;
  }
  return "";
}

/** Demo profiles as a revision-checked list, polled with If-None-Match like the config tables. */
export class ProfilesView {
  document: ProfilesDocument | null = null;
  etag = "";
  rows: ProfileDraft[] = [];
  private saved = "";
  private doc: Document;
  private api: DevApi;
  private notify: (message: string, error?: boolean) => void;

  constructor(doc: Document, api: DevApi, notify: (message: string, error?: boolean) => void) {
    this.doc = doc; this.api = api; this.notify = notify;
    this.$("profiles-form").addEventListener("input", () => { this.read(); this.validate(); });
    this.$("profiles-form").addEventListener("submit", (event) => { event.preventDefault(); void this.save(); });
    this.$("profiles-reset").addEventListener("click", () => void this.load(true).catch(this.failed));
    this.$("profile-add").addEventListener("click", () => {
      this.read();
      this.rows.push({ id: "", display_name: "", selections: "" });
      this.render();
    });
  }

  private $<T extends HTMLElement = HTMLElement>(id: string) { return this.doc.getElementById(id) as T; }
  get dirty() { return JSON.stringify(this.rows) !== this.saved; }
  private failed = (error: Error) => this.notify(`Profiles unavailable: ${error.message}`, true);

  /** An open draft is never replaced by polling. */
  async load(force = false) {
    if (this.dirty && !force) return;
    const loaded = await this.api.profiles(force ? "" : this.etag);
    if (!loaded || (this.dirty && !force)) return;
    this.show(loaded.document, loaded.etag);
  }

  private show(document: ProfilesDocument, etag: string) {
    this.document = document;
    this.etag = etag;
    this.rows = document.profiles.map(toDraft);
    this.saved = JSON.stringify(this.rows);
    this.$("profiles-meta").textContent = `revision ${document.revision}`;
    this.render();
  }

  private read() {
    for (const input of this.$("profile-rows").querySelectorAll<HTMLInputElement>("input[data-field]")) {
      const row = this.rows[Number(input.dataset.row)];
      if (row) row[input.dataset.field as (typeof FIELDS)[number]] = input.value.trim();
    }
  }

  private render() {
    this.$("profile-rows").replaceChildren(...this.rows.map((profile, index) => {
      const row = node(this.doc, "tr");
      for (const field of FIELDS) {
        const input = Object.assign(node(this.doc, "input"), { value: profile[field], maxLength: MAX[field],
          placeholder: PLACEHOLDERS[field] });
        input.dataset.row = String(index);
        input.dataset.field = field;
        input.setAttribute("aria-label", `Profile ${index + 1} ${field.replace("_", " ")}`);
        const cell = node(this.doc, "td");
        cell.append(input);
        row.append(cell);
      }
      const remove = Object.assign(node(this.doc, "button", "×", "button ghost danger"), { type: "button" });
      remove.setAttribute("aria-label", `Remove profile ${profile.id || index + 1}`);
      remove.addEventListener("click", () => { this.read(); this.rows.splice(index, 1); this.render(); });
      const cell = node(this.doc, "td");
      cell.append(remove);
      row.append(cell);
      return row;
    }));
    this.validate();
  }

  private validate() {
    const issue = profilesIssue(this.rows);
    this.$("profiles-issue").textContent = this.dirty ? issue : "";
    this.$<HTMLButtonElement>("profiles-save").disabled = !this.document || !this.dirty || Boolean(issue);
    this.$<HTMLButtonElement>("profiles-reset").disabled = !this.dirty;
    this.$("profiles-state").textContent = this.dirty ? "Unsaved changes" : "";
  }

  private async save() {
    const current = this.document;
    this.read();
    if (!current || profilesIssue(this.rows)) return;
    try {
      const saved = await this.api.saveProfiles(this.rows.map(toProfile), current.revision);
      this.show(saved, "");
      this.notify(`Saved profiles revision ${saved.revision}.`);
    } catch (error) {
      this.notify((error as Error).message, true);
      if (error instanceof ConflictError) this.$("profiles-state").textContent = "Conflict · discard to reload";
    }
  }
}
