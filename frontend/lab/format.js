export function clock(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
}

export function eventSeconds(event) {
  return event.match_time_seconds ?? event.elapsed_seconds ??
    ((event.minute ?? event.timeMin ?? 0) * 60 + (event.second ?? event.timeSec ?? 0));
}

export function replaySeconds(events) {
  // A late correction keeps its original event time; it must not rewind the clock.
  return events.reduce((latest, event) => Math.max(latest, eventSeconds(event)), 0);
}

export function title(value) {
  return String(value ?? 'Event').replaceAll('_', ' ').replace(/^./, char => char.toUpperCase());
}

export function teamNames(teams) {
  if (Array.isArray(teams)) return teams.map(team => typeof team === 'string' ? team : team.name || team.label || team.id);
  return ['home', 'away'].map(side => {
    const team = teams?.[side];
    return typeof team === 'string' ? team : team?.name || title(side);
  });
}
