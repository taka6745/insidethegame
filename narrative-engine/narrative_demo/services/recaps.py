"""Factual neutral summaries with retained children and nonoverlapping context."""
from ..models.clock import PERIOD_START_SECONDS, position

TIERS = [('minute', 60), ('five-minute', 300), ('ten-minute', 600), ('twenty-minute', 1200)]
SUMMARISED = ('goal', 'shot', 'corner', 'card', 'pass', 'foul', 'save')


def period_spans(payload, events):
    """Closed whole-minute coverage per observed period: (period, start, end, complete).

    A period closes at its `period_end` event (its final stoppage minute included)
    or when a later period has been observed; the current one at its last whole minute.
    """
    current = payload.snapshot.period or 1
    spans = []
    for period in sorted({event.get('period') or 1 for event in events} | {current}):
        if period > current:
            continue
        start = PERIOD_START_SECONDS.get(period, 0)
        inside = [event for event in events if position(event)[0] == period]
        ended = [event['match_time_seconds'] for event in inside if event['event_type'] == 'period_end']
        inside = [event['match_time_seconds'] for event in inside]
        if ended:
            end, complete = -(-ended[-1] // 60) * 60, True
        elif period < current:
            end, complete = (max(inside, default=start - 60) // 60 + 1) * 60, True
        else:
            end, complete = (payload.snapshot.clock_seconds or 0) // 60 * 60, False
        spans.append((period, start, max(start, end), complete))
    return spans


def build_recaps(payload, events):
    teams = {team['id']: team['name'] for team in payload.teams}
    archive = []

    def block(tier, period, start, stop):
        counts = {}
        for event in events:
            # Possession samples and touches are not narrative evidence of pressure.
            if position(event)[0] != period or not start <= event['match_time_seconds'] < stop \
                    or event['event_type'] not in SUMMARISED:
                continue
            key = (teams.get(event.get('team_id'), 'Unassigned'), event['event_type'])
            counts[key] = counts.get(key, 0) + 1
        text = '; '.join(f'{team}: {count} {kind} events' for (team, kind), count in sorted(counts.items()))
        archive.append({'id': f'recap:{tier}:p{period}:{start}:{stop}', 'match_id': payload.snapshot.match_id,
                        'tier': tier, 'period': period, 'start_seconds': start, 'end_seconds': stop,
                        'summary': text or 'No recorded key events in this interval.',
                        'created_cursor': payload.snapshot.cursor, 'child_ids': [],
                        'superseded_by': None, 'supersession_cursor': None})

    spans = period_spans(payload, events)
    for period, start, end, complete in spans:
        # Tiers align to the period's kick-off; stoppage minutes stay minute blocks
        # until the whole half closes.
        for tier, duration in TIERS:
            for begin in range(start, end - duration + 1, duration):
                block(tier, period, begin, begin + duration)
        if complete and end > start:
            block('half', period, start, end)

    for child in archive:
        parents = [row for row in archive if row['period'] == child['period']
                   and row['start_seconds'] <= child['start_seconds'] and row['end_seconds'] >= child['end_seconds']
                   and row['end_seconds'] - row['start_seconds'] > child['end_seconds'] - child['start_seconds']]
        if parents:
            parent = min(parents, key=lambda row: row['end_seconds'] - row['start_seconds'])
            child['superseded_by'] = parent['id']
            child['supersession_cursor'] = payload.snapshot.cursor
            parent['child_ids'].append(child['id'])

    # Select the broadest blocks that cover each period exactly; no repeated evidence.
    active = []
    for period, start, end, _ in spans:
        cursor = start
        while cursor < end:
            selected = max((row for row in archive if row['period'] == period and row['start_seconds'] == cursor),
                           key=lambda row: row['end_seconds'])
            active.append(selected)
            cursor = selected['end_seconds']
    period, _, end, _ = spans[-1]
    return {'blocks': active, 'archive': archive,
            'coverage': [{'period': p, 'start_seconds': s, 'end_seconds': e, 'complete': c} for p, s, e, c in spans],
            'coverage_end_seconds': end,
            'tail': [event for event in events if position(event) >= (period, end)],
            'key_events': [event for event in payload.events if event['event_type'] in ('goal', 'card', 'penalty')
                           or event.get('deleted') or event.get('revision', 1) > 1],
            'available_tiers': [name for name, _ in TIERS] + ['half'], 'complete': True,
            'synthetic': True}
