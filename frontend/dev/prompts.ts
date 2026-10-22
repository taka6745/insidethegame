import { node } from "../match/dom.ts";
import type { DevApi, PromptRole } from "./api.ts";

const PLACEHOLDER = /\{([a-z_]+)\}/g;
export const MAX_TEMPLATE = 20_000;

/** Same rule as the backend: `{name}` tokens; JSON braces are not placeholders. */
export function placeholders(template: string): string[] {
  return [...new Set([...template.matchAll(PLACEHOLDER)].map((m) => m[1]!))].sort();
}

export function check(template: string, required: readonly string[]) {
  const found = new Set(placeholders(template));
  const missing = required.filter((name) => !found.has(name));
  const extra = [...found].filter((name) => !required.includes(name));
  const issue = !template.trim() ? "Template is empty."
    : template.length > MAX_TEMPLATE ? `Keep the template under ${MAX_TEMPLATE.toLocaleString("en")} characters.`
    : missing.length ? `Missing ${missing.map((n) => `{${n}}`).join(", ")}.`
    : extra.length ? `Unknown ${extra.map((n) => `{${n}}`).join(", ")}; the engine cannot fill it.`
    : "";
  return { missing, extra, issue };
}

export class PromptsView {
  roles: PromptRole[] = [];
  role = "";
  private saved = "";
  private doc: Document;
  private api: DevApi;
  private notify: (message: string, error?: boolean) => void;
  private text: HTMLTextAreaElement;

  constructor(doc: Document, api: DevApi, notify: (message: string, error?: boolean) => void) {
    this.doc = doc; this.api = api; this.notify = notify;
    this.text = this.$<HTMLTextAreaElement>("prompt-template");
    this.text.addEventListener("input", () => this.validate());
    this.$("prompt-form").addEventListener("submit", (event) => { event.preventDefault(); void this.save(); });
    this.$("prompt-reset").addEventListener("click", () => { this.text.value = this.saved; this.validate(); });
  }

  private $<T extends HTMLElement = HTMLElement>(id: string) { return this.doc.getElementById(id) as T; }
  get dirty() { return this.text.value !== this.saved; }
  private get current() { return this.roles.find((r) => r.role === this.role); }

  async load(role = this.role) {
    this.roles = (await this.api.prompts()).roles;
    this.select(this.roles.some((r) => r.role === role) ? role : this.roles[0]?.role ?? "");
  }

  private select(role: string) {
    this.role = role;
    const tabs = this.$("prompt-tabs");
    tabs.replaceChildren(...this.roles.map((r) => {
      const tab = node(this.doc, "button", r.role);
      tab.type = "button";
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(r.role === role));
      tab.addEventListener("click", () => {
        if (r.role !== this.role && (!this.dirty || confirm("Discard unsaved prompt changes?"))) this.select(r.role);
      });
      return tab;
    }));
    const current = this.current;
    const active = current?.versions.find((v) => v.version === current.active_version);
    this.saved = this.text.value = active?.template ?? "";
    this.$("prompt-meta").textContent = current ? `· active v${current.active_version}` : "";
    this.renderVersions();
    this.validate();
  }

  private validate() {
    const required = this.current?.placeholders ?? [];
    const { missing, extra, issue } = check(this.text.value, required);
    const chip = (name: string, state: "ok" | "missing" | "extra") => {
      const element = node(this.doc, "span", `{${name}}`, "chip");
      element.dataset.state = state;
      element.title = { ok: "Present", missing: "Missing", extra: "Not a known placeholder" }[state];
      return element;
    };
    this.$("chips").replaceChildren(...required.map((name) => chip(name, missing.includes(name) ? "missing" : "ok")),
      ...extra.map((name) => chip(name, "extra")));
    this.$("prompt-issue").textContent = this.dirty ? issue : "";
    this.$<HTMLButtonElement>("prompt-save").disabled = !this.dirty || Boolean(issue);
    this.$<HTMLButtonElement>("prompt-reset").disabled = !this.dirty;
  }

  private renderVersions() {
    const current = this.current;
    this.$("versions").replaceChildren(...(current?.versions ?? []).map((v) => {
      const row = node(this.doc, "li");
      const when = new Date(v.created_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
      row.append(node(this.doc, "strong", `v${v.version}`), node(this.doc, "span", `${v.source} · ${when}`));
      if (v.version === current!.active_version) {
        const pill = node(this.doc, "span", "Active", "pill");
        pill.dataset.on = "";
        row.append(pill);
      } else {
        const button = node(this.doc, "button", v.version < current!.active_version ? "Roll back" : "Activate", "button ghost");
        button.type = "button";
        button.setAttribute("aria-label", `Activate ${current!.role} version ${v.version}`);
        button.addEventListener("click", () => void this.activate(v.version));
        row.append(button);
      }
      return row;
    }));
  }

  private async save() {
    const current = this.current;
    if (!current) return;
    try {
      const { version } = await this.api.savePrompt(current.role, this.text.value, current.active_version);
      this.saved = this.text.value;
      await this.load();
      this.notify(`Saved ${current.role} v${version}; the engine picks it up on its next read.`);
    } catch (error) {
      this.notify((error as Error).message, true);
    }
  }

  private async activate(version: number) {
    if (this.dirty && !confirm("Discard unsaved prompt changes?")) return;
    try {
      await this.api.activatePrompt(this.role, version);
      this.saved = this.text.value;
      await this.load();
      this.notify(`${this.role} v${version} is active.`);
    } catch (error) {
      this.notify((error as Error).message, true);
    }
  }
}
