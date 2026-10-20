import type { MatchEvent, MatchState, Snapshot, StatNumber } from "./types.ts";
import { isRecord } from "./types.ts";

const metricFormat = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });

export function clock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "PRE-MATCH";
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}
export function title(value: string | null | undefined): string {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
export function number(value: StatNumber): string {
  if (typeof value === "number") return metricFormat.format(value);
  if (value === null || value === undefined) return "—";
  return String(value);
}
export function statValue(card: { value?: StatNumber; unit?: string }): string {
  if (card.value == null || (typeof card.value === "number" && !Number.isFinite(card.value))) return "—";
  const unit = card.unit;
  return number(card.value) + (!unit || unit === "count" ? "" : unit === "%" ? "%" : ` ${unit}`);
}
const eventNames: Partial<Record<string, string>> = {
  shot: "Shot",
  goal: "Goal",
  pass: "Pass",
  corner: "Corner",
  card: "Card",
  save: "Save",
  tackle: "Tackle",
  clearance: "Clearance",
  interception: "Interception",
  foul: "Foul",
  touch: "Touch",
};
export function eventLabel(event: Pick<MatchEvent, "body_part" | "event_type">): string {
  return `${event.body_part === "head" ? "Headed " : ""}${(eventNames[String(event.event_type)] || title(event.event_type)).toLowerCase()}`.replace(
    /^./,
    (c) => c.toUpperCase(),
  );
}
export function latestEvents<T extends MatchEvent>(events: readonly T[], limit = 30): T[] {
  return [...events]
    .filter((event) => !event.deleted)
    .sort(
      (a, b) =>
        (b.period || 0) - (a.period || 0) ||
        b.match_time_seconds - a.match_time_seconds,
    )
    .slice(0, limit);
}
/** Only messages with a match and the three bounded lists are snapshots. */
function isSnapshot(value: unknown): value is Snapshot {
  return (
    isRecord(value) &&
    Boolean(value.match) &&
    Array.isArray(value.cards) &&
    Array.isArray(value.events) &&
    Array.isArray(value.narratives)
  );
}
export function currentSnapshot(previous: Snapshot, incoming: unknown): Snapshot;
export function currentSnapshot(
  previous: Snapshot | null | undefined,
  incoming: unknown,
): Snapshot | null | undefined;
export function currentSnapshot(
  previous: Snapshot | null | undefined,
  incoming: unknown,
): Snapshot | null | undefined {
  if (!isSnapshot(incoming)) return previous;
  if (
    previous?.match.run_id === incoming.match.run_id &&
    previous!.projection_epoch === incoming.projection_epoch &&
    Number(incoming.version) <= Number(previous!.version)
  )
    return previous;
  return {
    ...incoming,
    events: incoming.events.slice(-60),
    narratives: incoming.narratives.slice(-40),
    cards: incoming.cards.slice(0, 5),
  };
}

export function replayControls(match: MatchState) {
  const ready = match.status === "ready";
  const running = match.status === "running";
  const finished = ["finished", "completed"].includes(String(match.status));
  return {
    showStart: ready,
    startLabel: match.position ? "Resume match" : "Start match",
    showReset: !running && Boolean(match.position),
    progress: running
      ? `Replaying · ${match.position}/${match.total}`
      : finished
        ? "Demo complete"
        : ready
          ? match.position
            ? "Ready to resume"
            : "Forward-only replay"
          : "Replay interrupted",
  };
}
