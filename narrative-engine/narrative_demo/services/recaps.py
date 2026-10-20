"""Factual neutral summaries with retained children and nonoverlapping context."""
TIERS = [('minute', 60), ('five-minute', 300), ('ten-minute', 600), ('twenty-minute', 1200)]


def build_recaps(payload, events):
    end = (payload.snapshot.clock_seconds or 0) // 60 * 60
    teams = {team['id']: team['name'] for team in payload.teams}
    archive = []

    def block(tier, start, stop):
        selected = [event for event in events if start <= event['match_time_seconds'] < stop]
        counts = {}
        for event in selected:
            # Possession samples and touches are not narrative evidence of pressure.
            if event['event_type'] not in ('goal', 'shot', 'corner', 'card', 'pass', 'foul', 'save'):
                continue
            key = (teams.get(event.get('team_id'), 'Unassigned'), event['event_type'])
            counts[key] = counts.get(key, 0) + 1
        text = '; '.join(f'{team}: {count} {kind} events' for (team, kind), count in sorted(counts.items()))
        archive.append({'id': f'recap:{tier}:{start}:{stop}', 'match_id': payload.snapshot.match_id,
                        'tier': tier, 'start_seconds': start, 'end_seconds': stop,
                        'summary': text or 'No recorded key events in this interval.',
                        'created_cursor': payload.snapshot.cursor, 'child_ids': [],
                        'superseded_by': None, 'supersession_cursor': None})

    # Half boundaries are the nominal football clock. The recording plays faster.
    for half_start in range(0, end, 2700):
        half_end = min(half_start + 2700, end)
        for tier, duration in TIERS:
            for start in range(half_start, half_end - duration + 1, duration):
                block(tier, start, start + duration)
        if half_end == half_start + 2700:
            block('half', half_start, half_end)

    for child in archive:
        parents = [row for row in archive if row['start_seconds'] <= child['start_seconds']
                   and row['end_seconds'] >= child['end_seconds']
                   and row['end_seconds'] - row['start_seconds'] > child['end_seconds'] - child['start_seconds']]
        if parents:
            parent = min(parents, key=lambda row: row['end_seconds'] - row['start_seconds'])
            child['superseded_by'] = parent['id']
            child['supersession_cursor'] = payload.snapshot.cursor
            parent['child_ids'].append(child['id'])

    # Select the broadest blocks that cover the prefix exactly; no repeated evidence.
    active, cursor = [], 0
    while cursor < end:
        candidates = [row for row in archive if row['start_seconds'] == cursor]
        selected = max(candidates, key=lambda row: row['end_seconds'])
        active.append(selected)
        cursor = selected['end_seconds']
    return {'blocks': active, 'archive': archive, 'coverage_end_seconds': end,
            'tail': [event for event in events if event['match_time_seconds'] >= end],
            'key_events': [event for event in payload.events if event['event_type'] in ('goal', 'card')
                           or event.get('deleted') or event.get('revision', 1) > 1],
            'available_tiers': [name for name, _ in TIERS] + ['half'], 'complete': True,
            'synthetic': True}
