"""Translate canonical ETL deliveries into the observed revision set."""


def observed_events(deliveries):
    latest = {}
    for event in deliveries:
        identifier = event['event_id']
        previous = latest.get(identifier)
        if previous is None or event.get('revision', 1) > previous.get('revision', 1):
            latest[identifier] = event
    return sorted((row for row in latest.values() if not row.get('deleted', False)),
                  key=lambda row: (row['match_time_seconds'], row['event_id']))
