import type { MatchEvent, MatchSummary, Snapshot, StatNumber } from "./types.ts";
import { isRecord } from "./types.ts";

const metricFormat = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });

export function clock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "PRE-MATCH";
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}
/** Pre-match clock: time to kickoff, `KICK-OFF` once it is due, `PRE-MATCH` when unknown. */
export function countdown(kickoff: string | null | undefined, now = Date.now()): string {
  const at = kickoff ? new Date(kickoff).getTime() : NaN;
  if (!Number.isFinite(at)) return "PRE-MATCH";
  const left = Math.ceil((at - now) / 1000);
  return left > 0 ? `KO in ${clock(left)}` : "KICK-OFF";
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
    previous?.match.id === incoming.match.id &&
    previous!.projection_epoch === incoming.projection_epoch &&
    Number(incoming.version) <= Number(previous!.version)
  )
    return previous;
  return {
    ...incoming,
    events: incoming.events.slice(-60),
    // The viewer's bucket history: minute insights plus recaps and key moments.
    narratives: incoming.narratives.slice(-300),
    cards: incoming.cards.slice(0, 5),
    key_moments: (incoming.key_moments || []).slice(-100),
  };
}

/** Match status from the backend: `scheduled`, `live` or `finished`. */
export function isLive(status: unknown): boolean {
  return status === "live";
}
export function isFinished(status: unknown): boolean {
  return status === "finished";
}
/** Picker status line: live clock, kickoff time, or full time. */
export function matchStatus(match: Pick<MatchSummary, "status" | "clock_seconds" | "scheduled_kickoff">,
  locale?: string): string {
  if (isLive(match.status)) return `Live · ${clock(match.clock_seconds)}`;
  if (isFinished(match.status)) return "Full time";
  const kickoff = match.scheduled_kickoff ? new Date(match.scheduled_kickoff) : null;
  return kickoff && Number.isFinite(kickoff.getTime())
    ? `Kick-off ${kickoff.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })}`
    : "Scheduled";
}
