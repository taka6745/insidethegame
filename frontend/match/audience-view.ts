import { node } from "./dom.ts";
import type { Audience, Snapshot } from "./types.ts";

/** One dropdown of the match's enabled audience buckets, straight from the snapshot. */
export class AudienceView {
  document: Document;
  select: HTMLSelectElement;
  controls: HTMLElement;
  count = 0;
  live = false;
  busy = false;
  /** A live demo match keeps the bucket the viewer started with. */
  locked = false;
  choicesKey?: string;
  constructor(document: Document) {
    this.document = document;
    this.select = document.getElementById("audience-bucket") as HTMLSelectElement;
    this.controls = document.getElementById("audience-controls") as HTMLElement;
  }
  selection(): Audience {
    return { bucket_id: this.select.value };
  }
  connection(live: boolean) {
    this.live = live;
    this.setBusy(this.busy);
  }
  setBusy(busy: boolean) {
    this.busy = busy;
    // One bucket (or none) leaves nothing to switch to.
    this.select.disabled = busy || !this.live || this.count < 2 || this.locked;
    this.select.title = this.locked ? "Your perspective is fixed while the match is live." : "";
  }
  render(snapshot: Pick<Snapshot, "audience" | "audience_buckets"> & Partial<Pick<Snapshot, "match">>) {
    this.locked = snapshot.match?.status === "live";
    const buckets = snapshot.audience_buckets || [];
    const key = JSON.stringify(buckets);
    if (key !== this.choicesKey) {
      this.select.replaceChildren(...buckets.map(({ id, label }) => {
        const option = node(this.document, "option", label);
        option.value = id;
        return option;
      }));
      this.choicesKey = key;
      this.count = buckets.length;
      this.controls.hidden = !buckets.length;
    }
    if (snapshot.audience?.bucket_id) this.select.value = snapshot.audience.bucket_id;
    this.setBusy(this.busy);
  }
  /** The shown bucket's label, or null when the viewer has none. */
  label(snapshot: Pick<Snapshot, "audience" | "audience_buckets">): string | null {
    const id = snapshot.audience?.bucket_id;
    return (snapshot.audience_buckets || []).find((bucket) => bucket.id === id)?.label ?? null;
  }
}
