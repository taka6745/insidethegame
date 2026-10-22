import { node } from "../match/dom.ts";
import { CONFIG_TABLES, ConflictError } from "./api.ts";
import type { ConfigDocument, DevApi } from "./api.ts";

/** The draft as JSON, or why it cannot be saved. */
export function parseDraft(text: string): { value?: unknown; issue: string } {
  if (!text.trim()) return { issue: "The table cannot be empty." };
  try {
    const value: unknown = JSON.parse(text);
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? { value, issue: "" } : { issue: "The table must be a JSON object." };
  } catch (error) {
    return { issue: `Not valid JSON: ${(error as Error).message}` };
  }
}

/** Backend config tables as revision-checked JSON documents (same pattern as audiences and prompts). */
export class ConfigView {
  table: string = CONFIG_TABLES[0].id;
  document: ConfigDocument | null = null;
  etag = "";
  private saved = "";
  private doc: Document;
  private api: DevApi;
  private notify: (message: string, error?: boolean) => void;
  private text: HTMLTextAreaElement;

  constructor(doc: Document, api: DevApi, notify: (message: string, error?: boolean) => void) {
    this.doc = doc; this.api = api; this.notify = notify;
    this.text = this.$<HTMLTextAreaElement>("config-value");
    this.text.addEventListener("input", () => this.validate());
    this.$("config-form").addEventListener("submit", (event) => { event.preventDefault(); void this.save(); });
    this.$("config-reset").addEventListener("click", () => { this.text.value = this.saved; this.validate(); });
    this.$("config-reload").addEventListener("click", () => {
      if (!this.dirty || confirm("Discard your draft and load the saved version?")) void this.load(true).catch(this.failed);
    });
    this.tabs();
  }

  private $<T extends HTMLElement = HTMLElement>(id: string) { return this.doc.getElementById(id) as T; }
  get dirty() { return this.text.value !== this.saved; }
  private failed = (error: Error) => this.notify(`Config unavailable: ${error.message}`, true);

  private tabs() {
    this.$("config-tabs").replaceChildren(...CONFIG_TABLES.map((table) => {
      const tab = node(this.doc, "button", table.title);
      tab.type = "button";
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(table.id === this.table));
      tab.addEventListener("click", () => {
        if (table.id === this.table || (this.dirty && !confirm("Discard unsaved config changes?"))) return;
        this.table = table.id;
        this.document = null;
        this.etag = "";
        this.tabs();
        void this.load(true).catch(this.failed);
      });
      return tab;
    }));
    this.$("config-hint").textContent = CONFIG_TABLES.find((table) => table.id === this.table)?.hint ?? "";
  }

  /** Polled with If-None-Match; an open draft is never replaced. */
  async load(force = false) {
    if (this.dirty && !force) return;
    const table = this.table;
    const loaded = await this.api.table(table, force ? "" : this.etag);
    if (table !== this.table || !loaded) return;
    this.document = loaded.document;
    this.etag = loaded.etag;
    this.saved = this.text.value = JSON.stringify(loaded.document.value, null, 2);
    this.$("config-meta").textContent = `· revision ${loaded.document.revision}`;
    this.validate();
  }

  private validate() {
    const { issue } = parseDraft(this.text.value);
    this.$("config-issue").textContent = this.dirty ? issue : "";
    this.$<HTMLButtonElement>("config-save").disabled = !this.document || !this.dirty || Boolean(issue);
    this.$<HTMLButtonElement>("config-reset").disabled = !this.dirty;
    this.$("config-state").textContent = this.dirty ? "Unsaved changes" : "";
  }

  private async save() {
    const current = this.document;
    const { value, issue } = parseDraft(this.text.value);
    if (!current || issue) return;
    try {
      const { revision } = await this.api.saveTable(this.table, value, current.revision, this.etag);
      this.saved = this.text.value;
      await this.load(true);
      this.notify(`Saved ${this.table} revision ${revision}.`);
    } catch (error) {
      this.notify((error as Error).message, true);
      if (error instanceof ConflictError) this.$("config-state").textContent = "Conflict · reload to compare";
    }
  }
}
