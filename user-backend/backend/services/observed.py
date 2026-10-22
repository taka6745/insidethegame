"""Observed match history: the latest non-deleted revision of each received event."""


def observed(deliveries):
    """Ordered by (period, clock); stoppage repeats clock values, so delivery order breaks ties."""
    latest, first_seen = {}, {}
    for index, event in enumerate(deliveries):
        first_seen.setdefault(event.event_id, index)
        previous = latest.get(event.event_id)
        if previous is None or event.revision > previous.revision:
            latest[event.event_id] = event
    return sorted((e for e in latest.values() if not e.deleted),
                  key=lambda e: (e.period, e.match_time_seconds, first_seen[e.event_id]))
