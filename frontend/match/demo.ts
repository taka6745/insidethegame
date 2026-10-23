import { node } from "../shared/dom.ts";
import { DemoProgress, follow, type DemoStatus } from "./demo-progress.ts";
import { friendly, type Fetcher } from "./api.ts";

/** Our own sentence for the viewer (status-tagged, so `friendly()` shows it; any other error stays hidden). */
const said = (message: string, status = 0) => Object.assign(new Error(message), { status });

/** A start point the operator offers; `ready` is false until its seed is recorded. */
export interface DemoPoint { id: string; label: string; ready: boolean }
/** live_from: the start point's label when the demo began from a recorded seed, else null.
 * main_match_id: the live demo's main game, which the viewer opens by default. */
export interface DemoState {
  points: DemoPoint[]; live: boolean; live_from?: string | null; main_match_id?: string | null;
  runs?: { match_id: string }[];
  /** Seed-recording runs: they stop at their hold point, so viewers are never shown them. */
  recording?: { match_id: string }[];
  /** Start and cancel answer at once and run in turn: what is still queued, and how the last one ended. */
  pending?: string[]; last?: DemoOutcome | null;
  /** Skip ahead targets, offered while a demo plays (demo fast-forward). */
  skips?: { id: string; label: string }[];
}
/** A skip moves every demo run on by the same whole minutes; matchIds, follows and sessions carry on. */
export interface SkipResult { skipped_seconds: number; target: { label: string } }
interface DemoResult {
  started?: boolean; runs?: { match_id: string; kickoff: string }[]; cancelled?: string[]; live_from?: string | null;
  accepted?: boolean;
}
interface DemoOutcome extends DemoResult { action: string; ok: boolean; detail?: string }

/** The public demo controls (`/demo-api/`): one demo of three matches at a time, from a chosen start point. */
export class DemoApi {
  fetcher: Fetcher;
  constructor(fetcher: Fetcher = (...args) => globalThis.fetch(...args)) {
    this.fetcher = fetcher;
  }
  async call<T>(path: string, body?: unknown): Promise<T> {
    let response: Awaited<ReturnType<Fetcher>>;
    try {
      response = await this.fetcher(`/demo-api/${path}`, {
        method: body === undefined ? "GET" : "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      throw said("Can't reach the demo controls right now. Try again shortly.");  // never the raw network error
    }
    const data = await response.json().catch(() => ({})) as T & { detail?: unknown };
    if (!response.ok) throw said(typeof data.detail === "string" ? data.detail : "The demo could not be changed. Try again shortly.", response.status);
    return data;
  }
  state() { return this.call<DemoState>("state"); }
  status() { return this.call<DemoStatus>("status"); }
  start(point: string) { return this.settled("start", this.call<DemoResult>("start", { point })); }
  cancel() { return this.settled("cancel", this.call<DemoResult>("cancel", {})); }
  skip(target: string) { return this.call<SkipResult>("skip", { target }); }
  /** An accepted (queued) start or cancel: wait on /state until it has run, then return how it ended. */
  async settled(action: string, request: Promise<DemoResult>, pollMs = 1000, limit = 600): Promise<DemoResult> {
    const result = await request;
    if (!result.accepted) return result;
    for (let i = 0; i < limit; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, pollMs));
      const state = await this.state().catch(() => null);  // a cold or busy operator: keep waiting
      if (!state || state.pending?.length) continue;
      const last = state.last;
      if (last?.action !== action) return {};
      if (!last.ok) throw said(last.detail ?? "The demo could not be changed. Try again shortly.");
      return last;
    }
    throw said("The demo is taking longer than expected; check back shortly.");
  }
}

/** Start demo (with a start point) when nothing is on; Cancel demo while one is scheduled or live. */
export class DemoControls {
  document: Document;
  api: DemoApi;
  busy = false;
  live = false;
  /** The live demo's main game, and whether this viewer just started the demo (so it opens even from the picker). */
  main: string | null = null;
  /** The live demo's matches, and the seed-recording runs to hide. */
  runs = new Set<string>();
  recording = new Set<string>();
  started = false;
  progress?: DemoProgress;
  watching = false;
  onChange: () => void = () => {};
  notice: (message: string) => void = () => {};
  constructor(document: Document, api = new DemoApi()) {
    this.document = document;
    this.api = api;
    this.get("demo-start").addEventListener("click", () => void this.start());
    // Cancel asks in the page first; Escape or Keep watching closes the dialog without cancelling.
    const confirm = this.get<HTMLDialogElement>("demo-cancel-dialog");
    this.get("demo-cancel").addEventListener("click", () => {
      confirm.returnValue = "";
      confirm.showModal();
    });
    confirm.addEventListener("close", () => {
      if (confirm.returnValue === "confirm") void this.cancel();
    });
  }
  get<T extends HTMLElement = HTMLElement>(id: string) {
    return this.document.getElementById(id) as T;
  }
  render(state: DemoState) {
    this.live = state.live;
    this.main = state.live ? state.main_match_id ?? null : null;
    this.runs = new Set(state.live ? (state.runs ?? []).map((run) => run.match_id) : []);
    this.recording = new Set((state.recording ?? []).map((run) => run.match_id));
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
      this.notice(friendly(error, "The demo could not be changed. Try again shortly."));
    } finally {
      this.busy = false;
      await this.refresh();
      this.onChange();
    }
  }
  start() {
    const point = this.get<HTMLSelectElement>("demo-point").value || "kickoff";
    return this.act(async () => {
      this.started = true;
      void this.watch();  // the stages wake while the start runs
      const result = await this.api.start(point);
      if (!result.started) return "A demo is already on: pick one of its matches below.";
      // A seeded start's kickoff lies in the past (its clock starts at the point): say where it resumes instead.
      if (result.live_from) return `Demo resumes from ${result.live_from} in a few seconds.`;
      const first = result.runs?.[0]?.kickoff;
      return first ? `Demo starts at ${new Date(first).toLocaleTimeString("en-GB")}; matches appear about a minute before.` : "";
    });
  }
  cancel() {
    return this.act(async () => {
      await this.api.cancel();
      return "Demo cancelled.";
    });
  }
}

/** While a demo is on, only its matches are listed (when known), the main game first. Seed-recording runs are never
 * listed: they stop at their hold point, so a viewer opening one would see it freeze there. */
export function demoMatches<T extends { match_id: string; status?: string }>(
  matches: readonly T[], live: boolean, main: string | null = null,
  runs: ReadonlySet<string> = new Set(), recording: ReadonlySet<string> = new Set()): T[] {
  const listed = matches.filter((match) => !recording.has(match.match_id));
  if (!live) return listed;
  const shown = listed.filter((match) => match.status !== "finished" && (!runs.size || runs.has(match.match_id)));
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

/** In a demo match: Skip ahead to one of the operator's targets. The video catches up to the new live edge by itself
 * (liveCatchUp); the story fills in as the pipeline works through the skipped minutes. */
export async function showSkip(document: Document, matchId: string, api = new DemoApi()) {
  const box = document.getElementById("match-skip");
  const select = document.getElementById("match-skip-target") as HTMLSelectElement | null;
  const go = document.getElementById("match-skip-go") as HTMLButtonElement | null;
  const note = document.getElementById("match-skip-note");
  if (!box || !select || !go || !note) return;
  const render = async () => {
    const state = await api.state().catch(() => null);
    const ours = !!state?.live && (state.runs ?? []).some((run) => run.match_id === matchId);
    const skips = ours ? state?.skips ?? [] : [];
    select.replaceChildren(...skips.map(({ id, label }) => Object.assign(node(document, "option", label), { value: id })));
    box.hidden = !skips.length;
  };
  go.addEventListener("click", async () => {
    go.disabled = true;
    const label = select.selectedOptions[0]?.textContent ?? "";
    note.textContent = `Skipping ahead (${label})…`;
    try {
      const result = await api.skip(select.value);
      note.textContent = `Skipped ${Math.round(result.skipped_seconds / 60)} minutes for every demo match. ` +
        "The picture jumps ahead now; the story catches up over the next minutes.";
    } catch (error) {
      note.textContent = friendly(error, "Couldn't skip ahead. Try again shortly.");
    } finally {
      go.disabled = false;
      await render();
    }
  });
  await render();
}

/** In a match of a demo started from a recorded seed: say the story so far was generated earlier. */
export async function showLiveFrom(document: Document, matchId: string, api = new DemoApi()) {
  const from = document.getElementById("match-live-from");
  if (!from) return;
  try {
    const state = await api.state();
    const ours = state.live && state.live_from && (state.runs ?? []).some((run) => run.match_id === matchId);
    // A seed-recording run stops at its start point: say so instead of looking frozen there.
    const recording = (state.recording ?? []).some((run) => run.match_id === matchId);
    from.textContent = recording
      ? "This match is being recorded as a demo start point and pauses there. Start the demo or choose another match."
      : ours ? `The story so far was generated earlier on this pipeline; live from ${state.live_from}.` : "";
  } catch {
    from.textContent = "";  // No operator: not a demo.
  }
  from.hidden = !from.textContent;
}
