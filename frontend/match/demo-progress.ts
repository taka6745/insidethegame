import { node } from "../shared/dom.ts";

export interface Stage { id: string; ready: boolean }
export interface DemoStatus { live: boolean; matches: number; stages: Stage[] }

/** The pipeline in flow order: label, what is happening while it is not ready, and its icon (24 px paths). */
const STAGES: Record<string, { label: string; waiting: (matches: number) => string; icon: string }> = {
  "feed": { label: "Feed", waiting: () => "Waking the match feed", icon: "M3 6h18v12H3z M10 9l5 3-5 3z" },
  "event-hubs": { label: "Event Hubs", waiting: () => "Sending match info", icon: "M3 7h11M3 12h16M3 17h9 M18 7a1.5 1.5 0 1 0 .01 0" },
  "etl": { label: "ETL pipeline", waiting: () => "Waking the ETL", icon: "M5 6c0-2 14-2 14 0v12c0 2-14 2-14 0z M5 6c0 2 14 2 14 0 M5 12c0 2 14 2 14 0" },
  "service-bus": { label: "Service Bus", waiting: () => "Connecting the message bus", icon: "M3 6h18v12H3z M3 7l9 6 9-6" },
  "engine": { label: "Narrative engine", waiting: () => "Waking the narrative engine", icon: "M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" },
  "backend": { label: "Backend", waiting: () => "Waking the backend", icon: "M4 4h16v6H4z M4 14h16v6H4z" },
  "viewer": { label: "Viewer", waiting: (n) => `Starting ${n || "the"} matches`, icon: "M3 4h18v12H3z M9 20h6 M12 16v4" },
};
const SVG = "http://www.w3.org/2000/svg";

/** Every stage still waking: shown the moment a demo starts, before the operator has answered. */
export const pending = (matches = 0): DemoStatus =>
  ({ live: true, matches, stages: Object.keys(STAGES).map((id) => ({ id, ready: false })) });

/** Live readiness of every stage while a demo starts or wakes from zero; fades out when all are ready. */
export class DemoProgress {
  document: Document;
  root: HTMLElement;
  nodes = new Map<string, HTMLElement>();
  constructor(document: Document) {
    this.document = document;
    this.root = document.getElementById("demo-progress") as HTMLElement;
  }
  private build(stages: Stage[]) {
    const list = node(this.document, "ol", "", "pipeline");
    for (const { id } of stages) {
      const meta = STAGES[id];
      const item = node(this.document, "li", "", "stage");
      item.dataset.stage = id;
      const ring = node(this.document, "span", "", "stage-ring");
      if (meta && this.document.createElementNS) {
        const svg = this.document.createElementNS(SVG, "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("aria-hidden", "true");
        const path = this.document.createElementNS(SVG, "path");
        path.setAttribute("d", meta.icon);
        svg.append(path);
        ring.append(svg);
      }
      item.append(ring, node(this.document, "span", meta?.label ?? id, "stage-label"));
      list.append(item);
      this.nodes.set(id, item);
    }
    const video = node(this.document, "p", "video · HLS", "pipeline-video");
    const caption = node(this.document, "p", "", "pipeline-caption");
    caption.id = "demo-progress-caption";
    this.root.replaceChildren(list, video, caption);
  }
  /** Returns true when every stage is ready. */
  render(status: DemoStatus): boolean {
    if (this.nodes.size !== status.stages.length) this.build(status.stages);
    for (const stage of status.stages) {
      const item = this.nodes.get(stage.id);
      if (item) item.dataset.ready = stage.ready ? "yes" : "no";
    }
    const waiting = status.stages.find((stage) => !stage.ready);
    const caption = this.document.getElementById("demo-progress-caption");
    if (caption) caption.textContent = waiting ? STAGES[waiting.id]?.waiting(status.matches) ?? "Starting" : "Ready";
    this.root.hidden = false;
    this.root.dataset.done = waiting ? "no" : "yes";
    return !waiting;
  }
  hide() {
    this.root.hidden = true;
  }
}

/** Poll `status` until every stage is ready (true) or `limit` ms pass (false). The pending picture shows at once
 * (before the first answer), so a click never looks ignored while the operator wakes. */
export async function follow(status: () => Promise<DemoStatus>, view: Pick<DemoProgress, "render" | "hide">,
  { every = 1000, limit = 120_000, sleep = (ms: number) => new Promise((done) => setTimeout(done, ms)) } = {}) {
  const until = Date.now() + limit;
  view.render(pending());
  while (Date.now() < until) {
    try {
      if (view.render(await status())) {
        await sleep(every);  // Let the last ring settle before fading.
        view.hide();
        return true;
      }
    } catch { /* The operator itself may still be waking. */ }
    await sleep(every);
  }
  view.hide();
  return false;
}
