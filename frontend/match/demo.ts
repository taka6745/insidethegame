import { node } from "./dom.ts";
import { DemoProgress, follow, type DemoStatus } from "./demo-progress.ts";

/** A start point the operator offers; `ready` is false until its seed is recorded. */
export interface DemoPoint { id: string; label: string; ready: boolean }
/** live_from: the start point's label when the demo began from a recorded seed, else null.
 * main_match_id: the live demo's main game, which the viewer opens by default. */
export interface DemoState {
  points: DemoPoint[]; live: boolean; live_from?: string | null; main_match_id?: string | null;
  runs?: { match_id: string }[];
}
interface DemoResult {
  started?: boolean; runs?: { match_id: string; kickoff: string }[]; cancelled?: string[]; live_from?: string | null;
}

type Fetcher = (input: string, init: RequestInit) => Promise<Pick<Response, "ok" | "status" | "json">>;

/** The public demo controls (`/demo-api/`): one demo of three matches at a time, from a chosen start point. */
export class DemoApi {
  fetcher: Fetcher;
  constructor(fetcher: Fetcher = (...args) => globalThis.fetch(...args)) {
    this.fetcher = fetcher;
  }
  private async call<T>(path: string, body?: unknown): Promise<T> {
    const response = await this.fetcher(`/demo-api/${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json().catch(() => ({})) as T & { detail?: unknown };
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The demo could not be changed. Try again shortly.");
    return data;
  }
  state() { return this.call<DemoState>("state"); }
  status() { return this.call<DemoStatus>("status"); }
  start(point: string) { return this.call<DemoResult>("start", { point }); }
  cancel() { return this.call<DemoResult>("cancel", {}); }
}

/** Start demo (with a start point) when nothing is on; Cancel demo while one is scheduled or live. */
export class DemoControls {
  document: Document;
  api: DemoApi;
  busy = false;
  live = false;
  /** The live demo's main game, and whether this viewer just started the demo (so it opens even from the picker). */
  main: string | null = null;
  started = false;
  progress?: DemoProgress;
  watching = false;
  onChange: () => void = () => {};
  notice: (message: string) => void = () => {};
  constructor(document: Document, api = new DemoApi()) {
    this.document = document;
    this.api = api;
    this.get("demo-start").addEventListener("click", () => void this.start());
    this.get("demo-cancel").addEventListener("click", () => void this.cancel());
  }
  get<T extends HTMLElement = HTMLElement>(id: string) {
    return this.document.getElementById(id) as T;
  }
  render(state: DemoState) {
    this.live = state.live;
    this.main = state.live ? state.main_match_id ?? null : null;
    const select = this.get<HTMLSelectElement>("demo-point");
    const chosen = select.value;
    select.replaceChildren(...state.points.map((point) => {
      const option = node(this.document, "option", point.ready ? point.label : `${point.label} (not recorded yet)`);
      option.value = point.id;
      option.disabled = !point.ready;
      return option;
    }));
    if (state.points.some((point) => point.id === chosen && point.ready)) select.value = chosen;
    const from = this.get("demo-live-from");
    from.textContent = state.live && state.live_from
      ? `The story so far was generated earlier on this pipeline; live from ${state.live_from}.` : "";
    from.hidden = !from.textContent;
    this.get("demo-controls").hidden = false;
    this.sync();
  }
  sync() {
    this.get("demo-start").hidden = this.live;
    this.get("demo-point").hidden = this.live;
    this.get("demo-cancel").hidden = !this.live;
    for (const id of ["demo-start", "demo-cancel", "demo-point"]) this.get<HTMLButtonElement>(id).disabled = this.busy;
  }
  /** Show each stage waking until all are ready (after Start demo, or a cold load of a live demo). */
  async watch() {
    if (this.watching || !this.progress) return;
    this.watching = true;
    try {
      await follow(() => this.api.status(), this.progress);
    } finally {
      this.watching = false;
      this.onChange();
    }
  }
  async refresh() {
    try {
      this.render(await this.api.state());
      if (this.live && !this.watching && this.progress) {
        const status = await this.api.status();
        if (!status.stages.every((stage) => stage.ready)) void this.watch();
      }
    } catch {
      this.get("demo-controls").hidden = true;  // No operator (e.g. a deployment without demo controls).
    }
  }
  private async act(work: () => Promise<string>) {
    if (this.busy) return;
    this.busy = true;
    this.sync();
    try {
      this.notice(await work());
    } catch (error) {
      this.notice((error as Error).message);
    } finally {
      this.busy = false;
      await this.refresh();
      this.onChange();
    }
  }
  start() {
    const point = this.get<HTMLSelectElement>("demo-point").value || "kickoff";
    return this.act(async () => {
      const result = await this.api.start(point);
      this.started = true;
      void this.watch();
      if (!result.started) return "A demo is already on: pick one of its matches below.";
      // A seeded start's kickoff lies in the past (its clock starts at the point): say where it resumes instead.
      if (result.live_from) return `Demo resumes from ${result.live_from} in a few seconds.`;
      const first = result.runs?.[0]?.kickoff;
      return first ? `Demo starts at ${new Date(first).toLocaleTimeString("en-GB")}; matches appear about a minute before.` : "";
    });
  }
  cancel() {
    if (!globalThis.confirm?.("Cancel the demo for everyone watching it?")) return Promise.resolve();
    return this.act(async () => {
      await this.api.cancel();
      return "Demo cancelled.";
    });
  }
}

/** While a demo is on, only its matches are listed, the main game first. */
export function demoMatches<T extends { match_id: string; status?: string }>(
  matches: readonly T[], live: boolean, main: string | null = null): T[] {
  if (!live) return [...matches];
  const shown = matches.filter((match) => match.status !== "finished");
  return [...shown.filter((match) => match.match_id === main), ...shown.filter((match) => match.match_id !== main)];
}

/** The match to open instead of the picker: the live demo's main game, once listed, unless the viewer came to the
 * picker to choose another (`?choose`) and did not just start the demo. */
export function mainToOpen(controls: Pick<DemoControls, "live" | "main" | "started" | "watching">,
  listed: readonly { match_id: string }[], choosing: boolean): string | null {
  const main = controls.live ? controls.main : null;
  // Stay on the start-up progress until every stage is ready; it opens the main game when done.
  if (!main || controls.watching || (choosing && !controls.started)) return null;
  return listed.some((match) => match.match_id === main) ? main : null;
}

/** In a match of a demo started from a recorded seed: say the story so far was generated earlier. */
export async function showLiveFrom(document: Document, matchId: string, api = new DemoApi()) {
  const from = document.getElementById("match-live-from");
  if (!from) return;
  try {
    const state = await api.state();
    const ours = state.live && state.live_from && (state.runs ?? []).some((run) => run.match_id === matchId);
    from.textContent = ours ? `The story so far was generated earlier on this pipeline; live from ${state.live_from}.` : "";
  } catch {
    from.textContent = "";  // No operator: not a demo.
  }
  from.hidden = !from.textContent;
}
