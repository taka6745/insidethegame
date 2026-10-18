const metricFormat = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });

export function clock(seconds) {
  if (seconds === null || seconds === undefined) return "PRE-MATCH";
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}
export function title(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
export function number(value) {
  if (typeof value === "number") return metricFormat.format(value);
  if (value === null || value === undefined) return "—";
  return String(value);
}
export function eventLabel(event) {
  const names = {
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
  return `${event.body_part === "head" ? "Headed " : ""}${(names[event.event_type] || title(event.event_type)).toLowerCase()}`.replace(
    /^./,
    (c) => c.toUpperCase(),
  );
}
export function latestEvents(events, limit = 30) {
  return [...events]
    .filter((event) => !event.deleted)
    .sort(
      (a, b) =>
        (b.period || 0) - (a.period || 0) ||
        b.match_time_seconds - a.match_time_seconds,
    )
    .slice(0, limit);
}
export function currentSnapshot(previous, incoming) {
  if (
    !incoming?.match ||
    !Array.isArray(incoming.cards) ||
    !Array.isArray(incoming.events) ||
    !Array.isArray(incoming.narratives)
  )
    return previous;
  if (
    previous?.match.run_id === incoming.match.run_id &&
    previous.projection_epoch === incoming.projection_epoch &&
    Number(incoming.version) <= Number(previous.version)
  )
    return previous;
  return {
    ...incoming,
    events: incoming.events.slice(-60),
    narratives: incoming.narratives.slice(-40),
    cards: incoming.cards.slice(0, 3),
  };
}

export function replayControls(match) {
  const ready = match.status === "ready";
  const running = match.status === "running";
  const finished = ["finished", "completed"].includes(match.status);
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
