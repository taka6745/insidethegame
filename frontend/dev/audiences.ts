import { node } from "../match/dom.ts";
import { ConflictError } from "./api.ts";
import type { AudienceBucket, AudienceConfig, AudienceLayer, AudienceTemplate, DevApi, TemplateIndex } from "./api.ts";

export const MAX_BUCKETS = 48;
const KEY = /^[a-z0-9][a-z0-9_-]{0,63}$/;

export const MAX_LAYERS = 8;

/** The draft as saved: trimmed text; an option's `team` and `in_label` (not edited here) are kept. */
export function templateConfig(draft: AudienceConfig): AudienceConfig {
  return {
    layers: draft.layers.map((layer) => ({
      id: layer.id, description: layer.description.trim(),
      options: layer.options.map(({ id, label, description, team, in_label }) => ({
        id, description: description.trim(), ...(label?.trim() ? { label: label.trim() } : {}),
        ...(team ? { team } : {}), ...(typeof in_label === "boolean" ? { in_label } : {}),
      })),
    })),
    buckets: draft.buckets,
  };
}
export const MAX_OPTIONS = 20;

/** Every combination of one option per layer, in layer order. `enabled` is kept by selections, or,
 * when `before` (the layers `previous` was built from) is given, by option position, so renaming
 * a layer or option keeps its buckets' flags. A combination still selected keeps its id (one from
 * before a layer was added, as in migration 047, stays what viewers and profiles use). */
export function expandBuckets(layers: AudienceLayer[], previous: AudienceBucket[] = [], before?: AudienceLayer[]): AudienceBucket[] {
  const key = (selections: Record<string, string>) => layers.map((layer) => `${layer.id}=${selections[layer.id]}`).join("|");
  const position = (selections: Record<string, string>) =>
    before!.map((layer) => layer.options.findIndex((option) => option.id === selections[layer.id])).join();
  const enabled = new Set(previous.filter((bucket) => bucket.enabled).map((bucket) => (before ? position : key)(bucket.selections)));
  const ids = new Map(previous.map((bucket) => [key(bucket.selections), bucket.id]));
  let combinations: number[][] = layers.length ? [[]] : [];
  for (const layer of layers)
    combinations = combinations.flatMap((partial) => layer.options.map((_, index) => [...partial, index]));
  return combinations.map((indexes) => {
    const selections = Object.fromEntries(layers.map((layer, l) => [layer.id, layer.options[indexes[l]!]!.id]));
    return {
      id: ids.get(key(selections)) ?? layers.map((layer) => selections[layer.id]).join(":"),
      selections,
      enabled: enabled.has(before ? indexes.join() : key(selections)),
    };
  });
}

/** Why the draft cannot be saved, or "" (the backend validates again). */
export function draftIssue(config: AudienceConfig): string {
  if (!config.layers.length) return "Add at least one layer.";
  if (config.layers.length > MAX_LAYERS) return `${config.layers.length} layers; at most ${MAX_LAYERS}.`;
  const layerIds = new Set<string>();
  for (const layer of config.layers) {
    if (!KEY.test(layer.id)) return `Layer id "${layer.id}" must be lowercase letters, digits, - or _.`;
    if (layerIds.has(layer.id)) return `Layer id "${layer.id}" is used twice.`;
    layerIds.add(layer.id);
    if (!layer.description.trim()) return `Describe the ${layer.id} layer.`;
    if (!layer.options.length) return `Add an option to the ${layer.id} layer.`;
    if (layer.options.length > MAX_OPTIONS) return `${layer.id} has ${layer.options.length} options; at most ${MAX_OPTIONS}.`;
    const optionIds = new Set<string>();
    for (const option of layer.options) {
      if (!KEY.test(option.id)) return `Option id "${option.id}" in ${layer.id} must be lowercase letters, digits, - or _.`;
      if (optionIds.has(option.id)) return `Option "${option.id}" is used twice in ${layer.id}.`;
      optionIds.add(option.id);
      if (!option.description.trim()) return `Describe ${layer.id} option ${option.id}.`;
      if ((option.label ?? "").length > 60) return `Label of ${layer.id} option ${option.id} is over 60 characters.`;
    }
  }
  if (config.buckets.length > MAX_BUCKETS) return `${config.buckets.length} buckets; at most ${MAX_BUCKETS}.`;
  const long = config.buckets.find((bucket) => bucket.id.length > 100);
  if (long) return `Bucket id "${long.id.slice(0, 40)}…" is over 100 characters; shorten the option ids.`;
  return "";
}

const clone = (config: AudienceConfig): AudienceConfig => JSON.parse(JSON.stringify(config));

/** Audience templates per fixture: layers, options and descriptions, and which buckets are enabled.
 * Only enabled buckets are generated and offered to viewers. Saved with a revision check. */
export class AudiencesView {
  index: TemplateIndex = { templates: [], matches: [] };
  template: AudienceTemplate | null = null;
  draft: AudienceConfig | null = null;
  fixture = "";
  dirty = false;
  private doc: Document;
  private api: DevApi;
  private notify: (message: string, error?: boolean) => void;

  constructor(doc: Document, api: DevApi, notify: (message: string, error?: boolean) => void) {
    this.doc = doc; this.api = api; this.notify = notify;
    this.$<HTMLSelectElement>("catalogue").addEventListener("change", (event) => {
      const select = event.target as HTMLSelectElement;
      if (this.dirty && !confirm("Discard unsaved audience changes?")) {
        select.value = this.fixture;
        return;
      }
      this.select(select.value);
    });
    const form = this.$("layers-form");
    form.addEventListener("input", (event) => { if ((event.target as HTMLElement).dataset.field) this.edit(); });
    form.addEventListener("submit", (event) => { event.preventDefault(); void this.save(); });
    this.$("layers-reset").addEventListener("click", () => this.discard());
    this.$("layer-add").addEventListener("click", () => this.change((config) => {
      config.layers.push({ id: `layer-${config.layers.length + 1}`, description: "", options: [{ id: "option-1", label: "", description: "" }] });
    }));
  }

  private $<T extends HTMLElement = HTMLElement>(id: string) { return this.doc.getElementById(id) as T; }
  private get fixtures() {
    return [...new Set(["default", ...this.index.templates.map((t) => t.fixture), ...this.index.matches.map((m) => m.fixture)])].sort();
  }
  private get matches() { return this.index.matches.filter((m) => m.fixture === this.fixture); }

  private select(fixture: string) {
    this.fixture = fixture;
    this.template = this.draft = null;
    this.setDirty(false);
    void this.load().catch((error: Error) => this.notify(error.message, true));
  }

  /** Scope the panel to a fixture (from the Matches panel). */
  choose(fixture: string) {
    if (fixture !== this.fixture && this.dirty && !confirm("Discard unsaved audience changes?")) return;
    this.select(fixture);
    this.$("audiences").scrollIntoView?.({ block: "start" });
  }

  private setDirty(dirty: boolean) {
    this.dirty = dirty;
    const issue = this.draft ? draftIssue(this.draft) : "";
    this.$("layers-issue").textContent = dirty ? issue : "";
    this.$<HTMLButtonElement>("layers-save").disabled = !dirty || Boolean(issue);
    this.$<HTMLButtonElement>("layers-reset").disabled = !dirty;
    this.$("layers-state").textContent = dirty ? "Unsaved changes" : "";
  }

  /** Polled: the template is replaced only while nothing is being edited. */
  async load(force = false) {
    this.index = await this.api.templates();
    const fixtures = this.fixtures;
    if (!fixtures.includes(this.fixture))
      this.fixture = fixtures.find((f) => this.index.matches.some((m) => m.fixture === f)) ?? fixtures[0] ?? "";
    const select = this.$<HTMLSelectElement>("catalogue");
    const labels = fixtures.map((f) => {
      const live = this.index.matches.filter((m) => m.fixture === f).length;
      return [f, live ? `${f} · ${live} match${live === 1 ? "" : "es"}` : f];
    });
    if ([...select.options].map((o) => o.textContent).join() !== labels.map(([, l]) => l).join())
      select.replaceChildren(...labels.map(([value, label]) => Object.assign(node(this.doc, "option", label), { value })));
    select.value = this.fixture;
    if (this.fixture && (!this.dirty || force)) {
      const fixture = this.fixture, template = await this.api.template(fixture);
      if (fixture !== this.fixture || (this.dirty && !force)) return;
      const changed = force || template.revision !== this.template?.revision;
      this.template = template;
      if (changed) {
        this.draft = clone(template.config);
        this.render();
        this.setDirty(false);
      }
    }
    this.renderMode();
  }

  /** Back to the saved template (reloaded, so a conflict shows the other editor's version). */
  private discard() {
    this.setDirty(false);
    void this.load(true).catch((error: Error) => this.notify(error.message, true));
  }

  /** Structural change (add/remove): read the form, apply, re-expand buckets, re-render. */
  private change(apply: (config: AudienceConfig) => void) {
    if (!this.draft) return;
    this.read();
    apply(this.draft);
    this.draft.buckets = expandBuckets(this.draft.layers, this.draft.buckets);
    this.render();
    this.setDirty(true);
  }

  /** Text edits keep focus: only the bucket table re-renders. */
  private edit() {
    if (!this.draft) return;
    const before = clone(this.draft).layers;
    this.read();
    this.draft.buckets = expandBuckets(this.draft.layers, this.draft.buckets, before);
    this.renderBuckets();
    this.setDirty(true);
  }

  private read() {
    const draft = this.draft!;
    for (const input of this.$("layers").querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("[data-field]")) {
      const layer = draft.layers[Number(input.dataset.layer)];
      if (!layer) continue;
      const target = (input.dataset.option === undefined ? layer : layer.options[Number(input.dataset.option)]!) as unknown as Record<string, string>;
      target[input.dataset.field!] = input.dataset.field === "id" ? input.value.trim() : input.value;
    }
  }

  private input(kind: "input" | "textarea", value: string, label: string, data: Record<string, string>, max: number) {
    const field = Object.assign(node(this.doc, kind), { value, maxLength: max }) as HTMLInputElement | HTMLTextAreaElement;
    field.setAttribute("aria-label", label);
    if (kind === "textarea") (field as HTMLTextAreaElement).rows = 2;
    Object.assign(field.dataset, data);
    return field;
  }

  private button(text: string, label: string, action: () => void, className = "button ghost") {
    const button = Object.assign(node(this.doc, "button", text, className), { type: "button" });
    button.setAttribute("aria-label", label);
    button.addEventListener("click", action);
    return button;
  }

  private render() {
    const layers = this.draft?.layers ?? [];
    this.$("layers").replaceChildren(...layers.map((layer, l) => {
      const group = node(this.doc, "fieldset", "", "layer");
      const head = node(this.doc, "div", "", "layer-head");
      head.append(
        this.input("input", layer.id, `Layer ${l + 1} id`, { layer: String(l), field: "id" }, 64),
        this.button("Remove layer", `Remove layer ${layer.id}`, () => this.change((c) => { c.layers.splice(l, 1); }), "button ghost danger"),
      );
      const options = node(this.doc, "div", "", "options");
      options.append(...layer.options.map((option, o) => {
        const row = node(this.doc, "div", "", "option-row");
        const data = { layer: String(l), option: String(o) };
        row.append(
          this.input("input", option.id, `${layer.id} option ${o + 1} id`, { ...data, field: "id" }, 64),
          this.input("input", option.label ?? "", `${layer.id} option ${option.id} viewer label`, { ...data, field: "label" }, 60),
          this.input("textarea", option.description, `${layer.id} option ${option.id} description`, { ...data, field: "description" }, 600),
          this.button("×", `Remove ${layer.id} option ${option.id}`, () => this.change((c) => { c.layers[l]!.options.splice(o, 1); }), "button ghost danger"),
        );
        return row;
      }));
      group.append(
        head,
        this.input("textarea", layer.description, `${layer.id} layer description`, { layer: String(l), field: "description" }, 600),
        options,
        this.button("Add option", `Add an option to ${layer.id}`, () => this.change((c) => {
          c.layers[l]!.options.push({ id: `option-${c.layers[l]!.options.length + 1}`, label: "", description: "" });
        })),
      );
      return group;
    }));
    this.renderBuckets();
  }

  private renderMode() {
    const template = this.template, matches = this.matches;
    this.$("audience-mode").textContent = !template ? "No audience template yet."
      : `Fixture template · revision ${template.revision}${template.inherited ? " · inherited from the default until saved" : ""}. `
        + `${matches.length ? `Matches: ${matches.map((m) => m.match_id).join(", ")}. ` : "No matches of this fixture now. "}`
        + "Only enabled buckets are written for and offered to viewers.";
  }

  private renderBuckets() {
    const draft = this.draft;
    this.$("buckets").replaceChildren(...(draft?.buckets ?? []).map((bucket, index) => {
      const row = node(this.doc, "tr");
      const box = Object.assign(node(this.doc, "input"), { type: "checkbox", checked: bucket.enabled });
      box.setAttribute("aria-label", `Enable ${bucket.id}`);
      box.addEventListener("change", () => {
        draft!.buckets[index]!.enabled = box.checked;
        this.setDirty(true);
      });
      const label = node(this.doc, "label", "", "pin");
      label.append(box, node(this.doc, "span", "Enabled"));
      const cells = [node(this.doc, "td", bucket.id), node(this.doc, "td")];
      cells[0]!.title = Object.entries(bucket.selections).map(([k, v]) => `${k}: ${v}`).join(" · ");
      cells[1]!.append(label);
      row.append(...cells);
      return row;
    }));
    this.$("bucket-count").textContent = draft
      ? `${draft.buckets.filter((b) => b.enabled).length} of ${draft.buckets.length} enabled` : "";
  }

  private async save() {
    const template = this.template, draft = this.draft;
    if (!template || !draft) return;
    this.read();
    const issue = draftIssue(draft);
    if (issue) return this.notify(issue, true);
    try {
      const { revision } = await this.api.saveTemplate(this.fixture, templateConfig(draft), template.revision);
      this.setDirty(false);
      this.notify(`Saved ${this.fixture} revision ${revision}; its matches follow the template.`);
      await this.load(true);
    } catch (error) {
      this.notify((error as Error).message, true);
      if (error instanceof ConflictError) this.$("layers-state").textContent = "Conflict · discard to reload";
    }
  }
}
