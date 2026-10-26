import { node } from "../shared/dom.ts";
import { DemoProgress, follow, type DemoStatus } from "./demo-progress.ts";
import { friendly, type Fetcher } from "./api.ts";
import { clock, isLive } from "./format.ts";
import type { TimerId, Timers } from "./types.ts";

/** Our own sentence for the viewer (status-tagged, so `friendly()` shows it; any other error stays hidden). */
const said = (message: string, status = 0) => Object.assign(new Error(message), { status });

/** A start point the operator offers; `ready` is false until its seed is recorded. */
export interface DemoPoint { id: string; label: string; ready: boolean }
/** live_from: the start point's label when the demo began from a recorded seed, else null.
 * main_match_id: the live demo's main game, which the viewer opens by default. */
export interface DemoState {
  points: DemoPoint[]; live: boolean; live_from?: string | null; main_match_id?: string | null;
  /** The feed's runs: `kickoff` moves on a skip, so (now − kickoff) is the true clock while the backend catches up. */
  runs?: DemoRun[];
  /** Seed-recording runs: they stop at their hold point, so viewers are never shown them. */
  recording?: { match_id: string }[];
  /** Start and cancel answer at once and run in turn: what is still queued, and how the last one ended. */
  pending?: string[]; last?: DemoOutcome | null;
  /** Skip ahead targets, offered while a demo plays (demo fast-forward). */
  skips?: { id: string; label: string }[];
}
export interface DemoRun { match_id: string; kickoff?: string }
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
  feedRuns: DemoRun[] = [];
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
    this.feedRuns = state.live ? state.runs ?? [] : [];
    this.runs = new Set(this.feedRuns.map((run) => run.match_id));
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
    this.progress.onStop = () => void this.stop();
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
      // No operator (e.g. a deployment without demo controls); one still waking after this viewer's Start stays.
      if (!this.started) this.get("demo-controls").hidden = true;
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
      if (this.progress) this.progress.awaitLive = true;  // warm stages alone are not a running demo
      void this.watch();  // the stages wake while the start runs
      const result = await this.api.start(point).finally(() => { if (this.progress) this.progress.awaitLive = false; });
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
  /** Stop from the spin-up picture: cancels whatever the start is doing (the operator runs start, then cancel). */
  async stop() {
    this.progress?.hide();
    this.started = false;
    try {
      await this.api.cancel();
      this.notice("Demo stopped.");
    } catch (error) {
      this.notice(friendly(error, "The demo could not be stopped. Try again shortly."));
    }
    await this.refresh();
    this.onChange();
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

/** The picker's clocks from the feed's runs ((now − kickoff), the true clock after a skip) while the backend's
 * watermark catches up; a match without a run keeps the backend's clock. */
export function withRunClocks<T extends { match_id: string; status?: string; clock_seconds?: number | null }>(
  matches: readonly T[], runs: readonly DemoRun[], now = Date.now()): T[] {
  const kickoffs = new Map(runs.map((run) => [run.match_id, Date.parse(run.kickoff ?? "")]));
  return matches.map((match) => {
    const at = kickoffs.get(match.match_id);
    return at === undefined || !Number.isFinite(at) || !isLive(match.status) ? match
      : { ...match, clock_seconds: Math.max(0, Math.floor((now - at) / 1000)) };
  });
}

export type SkipOutcome = "reached" | "timeout";
export interface SkipTimers extends Timers {
  setInterval(callback: () => void, delay: number): TimerId;
  clearInterval(id: TimerId): void;
}
/** What the overlay reads from each state reaching the page: the match clock and the story's clocks. */
export interface SkipState { match: { clock_seconds?: number | null }; narratives?: readonly { clock_seconds?: number | null }[] }
/** Dismiss this close to the target: the last snapshots arrive as the pipeline settles. */
const SKIP_NEAR_SECONDS = 30;
const SKIP_MIN_TIMEOUT_MS = 90_000;

/** Skip ahead: a blocking picture of the match clock running from the clock at the click to the skip's target,
 * driven by the clocks of the states reaching the page. Everything else is frozen (`onFreeze`) while it is up;
 * it dismisses near the target, or after a timeout so no viewer is ever stuck behind it. */
export class SkipOverlay {
  document: Document;
  timers: SkipTimers;
  from = 0;
  target: number | null = null;
  latest = 0;
  shown = 0;
  /** The story for the skipped span has started arriving: an insight clocked past the click. */
  story = false;
  onFreeze: (on: boolean) => void = () => {};
  private settle: ((outcome: SkipOutcome) => void) | null = null;
  private timeout: TimerId = null;
  private ticker: TimerId = null;
  constructor(document: Document, timers: SkipTimers = globalThis) {
    this.document = document;
    this.timers = timers;
  }
  get up() { return this.settle !== null; }
  private get<T extends HTMLElement = HTMLElement>(id: string) { return this.document.getElementById(id) as T | null; }
  private text(id: string, value: string) {
    const element = this.get(id);
    if (element) element.textContent = value;
  }
  /** Show at once, before the operator answers: `seconds` is the target's own guess (null when its label says
   * nothing); `retarget` corrects it from the response. Resolves when dismissed. */
  show(from: number, seconds: number | null, label: string): Promise<SkipOutcome> {
    this.fail();
    this.from = this.latest = this.shown = from;
    this.target = null;
    this.story = false;
    this.text("match-skip-title", `Skipping ahead ${label}…`);
    if (seconds !== null) this.retarget(seconds);
    else this.arm(SKIP_MIN_TIMEOUT_MS);
    this.render();
    const root = this.get("match-skip-overlay");
    if (root) root.hidden = false;
    this.onFreeze(true);
    this.ticker = this.timers.setInterval(() => this.tick(), 100);
    return new Promise((resolve) => { this.settle = resolve; });
  }
  retarget(seconds: number) {
    this.target = this.from + seconds;
    this.text("match-skip-title", `Skipping ahead to ${Math.round(this.target / 60)}′`);
    this.arm(Math.max(SKIP_MIN_TIMEOUT_MS, seconds * 100));
    this.render();
  }
  private arm(ms: number) {
    this.timers.clearTimeout(this.timeout);
    this.timeout = this.timers.setTimeout(() => this.finish("timeout"), ms);
  }
  /** A state reached the page: its clock runs the readout; an insight past the click means the story caught up. */
  update(state: SkipState) {
    if (!this.up) return;
    const seconds = Number(state.match.clock_seconds);
    if (Number.isFinite(seconds)) this.latest = Math.max(this.latest, seconds);
    if ((state.narratives ?? []).some((n) => Number(n.clock_seconds) > this.from)) this.story = true;
  }
  /** Run the readout towards the latest clock, fast when far behind; dismiss once it is near the target and the
   * story has caught up (the clock alone leaves the insights still trickling in). */
  tick() {
    if (!this.up) return;
    if (this.shown < this.latest)
      this.shown = Math.min(this.latest, this.shown + Math.max(1, Math.ceil((this.latest - this.shown) / 20)));
    this.render();
    if (this.target !== null && this.story && this.shown >= this.target - SKIP_NEAR_SECONDS) this.finish("reached");
  }
  private render() {
    this.text("match-skip-clock", clock(this.shown));
    this.text("match-skip-range", this.target === null ? `from ${clock(this.from)}`
      : `${clock(this.from)} → ${clock(this.target)}`);
    const fill = this.get("match-skip-fill");
    const span = this.target === null ? 0 : this.target - this.from;
    if (fill) fill.style.width = `${span > 0 ? Math.min(100, Math.round(100 * (this.shown - this.from) / span)) : 0}%`;
  }
  /** The request failed: take the picture down without a result. */
  fail() {
    if (this.up) this.finish(null);
  }
  private finish(outcome: SkipOutcome | null) {
    const settle = this.settle;
    this.settle = null;
    this.timers.clearTimeout(this.timeout);
    this.timers.clearInterval(this.ticker);
    const root = this.get("match-skip-overlay");
    if (root) root.hidden = true;
    this.onFreeze(false);
    if (outcome && settle) settle(outcome);
  }
}

/** The seconds a target's label promises: "+20′" is relative, "65′" a point on the clock; else unknown. */
export function labelSeconds(label: string, from: number): number | null {
  const match = /(\+?)\s*(\d+)/.exec(label);
  if (!match) return null;
  const seconds = Number(match[2]) * 60;
  const ahead = match[1] ? seconds : seconds - from;
  return ahead > 0 ? ahead : null;
}

export interface SkipOptions {
  overlay?: SkipOverlay;
  /** The match clock shown now (null before kick-off). */
  clock?: () => number | null | undefined;
  /** Client caches: `flush` once the skip is accepted (held states, replay pages, an open replay), `resync` after
   * the overlay goes so the picture is fetched fresh. */
  caches?: { flush(): void; resync(): Promise<void> | void };
}

/** In a demo match: Skip ahead to one of the operator's targets. The overlay blocks the page while the clock runs
 * from the clock at the click to the target; the video catches up to the new live edge by itself (liveCatchUp). */
export async function showSkip(document: Document, matchId: string, api = new DemoApi(),
  { overlay, clock: shownClock = () => null, caches }: SkipOptions = {}) {
  const box = document.getElementById("match-skip");
  const targets = document.getElementById("match-skip-targets");
  const note = document.getElementById("match-skip-note");
  if (!box || !targets || !note) return;
  let busy = false;
  const skip = async (id: string, label: string) => {
    if (busy) return;
    busy = true;
    for (const button of targets.querySelectorAll("button")) button.disabled = true;
    note.textContent = `Skipping ahead ${label}…`;
    const from = Math.max(0, Number(shownClock()) || 0);
    const picture = overlay?.show(from, labelSeconds(label, from), label);
    try {
      const result = await api.skip(id);
      caches?.flush();
      overlay?.retarget(result.skipped_seconds);
      const outcome = await (picture ?? "reached");
      await caches?.resync();
      note.textContent = outcome === "timeout" ? "Still catching up; the clock will settle shortly."
        : `Skipped to ${Math.round((from + result.skipped_seconds) / 60)}′ in every demo match.`;
    } catch (error) {
      overlay?.fail();
      note.textContent = friendly(error, "Couldn't skip ahead. Try again shortly.");
    } finally {
      busy = false;
      await render();
    }
  };
  const render = async () => {
    const state = await api.state().catch(() => null);
    const ours = !!state?.live && (state.runs ?? []).some((run) => run.match_id === matchId);
    const skips = ours ? state?.skips ?? [] : [];
    targets.replaceChildren(...skips.map(({ id, label }) => {
      const button = node(document, "button", label, "demo-skip-target");
      button.type = "button";
      button.addEventListener("click", () => void skip(id, label));
      return button;
    }));
    box.hidden = !skips.length;
  };
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
      : ours ? `Live from ${state.live_from} · the story so far was generated earlier on this pipeline.` : "";
  } catch {
    from.textContent = "";  // No operator: not a demo.
  }
  from.hidden = !from.textContent;
}
