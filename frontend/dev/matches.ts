import { node } from "../match/dom.ts";
import type { DemoSettings, DevApi, PurgeTarget, Recording, Run } from "./api.ts";

export function clock(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** Summary of one purge across owners, e.g. "feed 3 · etl 812 · …". */
export function purgeSummary(results: { owner: string; result: { purged: Record<string, number> } }[]) {
  return results.map(({ owner, result }) =>
    `${owner} ${Object.values(result.purged ?? {}).reduce((sum, rows) => sum + (Number(rows) || 0), 0)}`).join(" · ");
}

/** Feed recordings and runs: start a fixture at the next minute, purge one match or all. */
export class MatchesView {
  recordings: Recording[] = [];
  runs: Run[] = [];
  demo: DemoSettings | null = null;
  busy = false;
  /** Selecting a run scopes the audiences panel to its fixture's template. */
  onSelect: (fixture: string) => void = () => {};
  private doc: Document;
  private api: DevApi;
  private notify: (message: string, error?: boolean) => void;
  private confirm: (message: string) => boolean;

  constructor(doc: Document, api: DevApi, notify: (message: string, error?: boolean) => void,
    confirmAction: (message: string) => boolean = (message) => confirm(message)) {
    this.doc = doc; this.api = api; this.notify = notify; this.confirm = confirmAction;
    this.$("purge-all").addEventListener("click", () => void this.purge({ all: true }));
    this.$("demo-save").addEventListener("click", () => void this.saveDemo());
  }

  private $<T extends HTMLElement = HTMLElement>(id: string) { return this.doc.getElementById(id) as T; }

  async load() {
    const [recordings, runs, demo] = await Promise.allSettled([this.api.recordings(), this.api.runs(), this.api.demo()]);
    if (recordings.status === "fulfilled") this.recordings = recordings.value;
    if (runs.status === "fulfilled") this.runs = runs.value;
    if (demo.status === "fulfilled" && demo.value.revision !== this.demo?.revision) {
      this.demo = demo.value;
      const { revision: _, ...settings } = demo.value;
      this.$<HTMLTextAreaElement>("demo-settings").value = JSON.stringify(settings, null, 2);
    }
    this.render();
    const failed = [recordings, runs].find((result) => result.status === "rejected");
    this.$("feed-state").textContent = failed ? `Feed unavailable: ${(failed.reason as Error).message}` : "";
  }

  render() {
    this.$("recordings").replaceChildren(...(this.recordings.length ? this.recordings.map((recording) => {
      const row = node(this.doc, "li");
      const teams = recording.teams?.map((team) => team.name).join(" v ");
      const info = node(this.doc, "span", "", "row-info");
      info.append(node(this.doc, "strong", recording.description || teams || recording.fixture),
        node(this.doc, "span", [recording.fixture, recording.duration_seconds ? clock(recording.duration_seconds) : null,
          recording.synthetic ? "synthetic" : null].filter(Boolean).join(" · "), "muted"));
      const start = node(this.doc, "button", "Start", "button primary");
      start.type = "button";
      start.disabled = this.busy;
      start.setAttribute("aria-label", `Start ${recording.fixture} at the next minute`);
      start.addEventListener("click", () => void this.start(recording.fixture));
      row.append(info, start);
      return row;
    }) : [node(this.doc, "li", "No recordings in the feed catalogue.", "muted")]));
    this.$("runs").replaceChildren(...(this.runs.length ? this.runs.map((run) => {
      const row = node(this.doc, "li");
      row.dataset.status = run.status;
      const info = node(this.doc, "span", "", "row-info");
      const kickoff = new Date(run.kickoff);
      info.append(node(this.doc, "strong", run.match_id),
        node(this.doc, "span", [run.status === "scheduled" && Number.isFinite(kickoff.getTime())
          ? `kick-off ${kickoff.toLocaleTimeString("en-GB")}` : `video ${clock(run.video_seconds)}`,
          `seq ${run.seq ?? 0}`].join(" · "), "muted"));
      const pill = node(this.doc, "span", run.status, "pill");
      if (run.status === "live") pill.dataset.on = "";
      const view = node(this.doc, "a", "Open", "button ghost");
      view.href = `/?match=${encodeURIComponent(run.match_id)}`;
      view.target = "_blank";
      view.rel = "noopener";
      const audiences = node(this.doc, "button", "Audiences", "button ghost");
      audiences.type = "button";
      audiences.addEventListener("click", () => this.onSelect(run.fixture));
      const purge = node(this.doc, "button", "Purge", "button ghost danger");
      purge.type = "button";
      purge.disabled = this.busy;
      purge.setAttribute("aria-label", `Purge ${run.match_id}`);
      purge.addEventListener("click", () => void this.purge({ match_id: run.match_id }));
      const actions = node(this.doc, "span", "", "row-actions");
      actions.append(pill, view, audiences, purge);
      row.append(info, actions);
      return row;
    }) : [node(this.doc, "li", "No runs. Start a recording above.", "muted")]));
    this.$<HTMLButtonElement>("purge-all").disabled = this.busy;
  }

  private async run(work: () => Promise<void>) {
    if (this.busy) return;
    this.busy = true;
    this.render();
    try { await work(); }
    catch (error) { this.notify((error as Error).message, true); }
    finally {
      this.busy = false;
      await this.load().catch(() => this.render());
    }
  }

  start(fixture: string) {
    return this.run(async () => {
      const run = await this.api.startRun(fixture);
      this.notify(`${run.match_id} starts at ${new Date(run.kickoff).toLocaleTimeString("en-GB")}; MA1 arrives about a minute before.`);
    });
  }

  saveDemo() {
    return this.run(async () => {
      if (!this.demo) throw new Error("Demo settings have not loaded yet.");
      let edited: Omit<DemoSettings, "revision">;
      try { edited = JSON.parse(this.$<HTMLTextAreaElement>("demo-settings").value); }
      catch { throw new Error("Demo settings must be valid JSON."); }
      this.demo = await this.api.saveDemo({ ...edited, revision: this.demo.revision });
      this.notify("Demo settings saved.");
    });
  }

  purge(target: PurgeTarget) {
    const what = "all" in target ? "every match" : target.match_id;
    if (!this.confirm(`Purge ${what} from the feed, ETL, narrative engine and backend? Configuration stays.`))
      return Promise.resolve();
    return this.run(async () => {
      const results = await this.api.purge(target, (owner) => { this.$("feed-state").textContent = `Purging ${what}: ${owner}…`; });
      this.notify(`Purged ${what}: ${purgeSummary(results)} rows.`);
    });
  }
}
