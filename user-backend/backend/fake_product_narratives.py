"""Synthetic upstream-owned audience messages for the removable product demo.

These factual templates are fixtures, not generated commentary or a licensed feed.
"""
STAT_ORDER = {
    'simple': ('goals', 'cards', 'shots'),
    'casual': ('goals', 'shots', 'corners'),
    'experienced': ('shots', 'passes', 'cards'),
    'analytical': ('shots', 'corners', 'passes'),
}


def viewer_narratives(payload, events):
    teams = {t['id']: t['name'] for t in payload.teams}
    players = {p['id']: p['name'] for p in payload.players}
    events = sorted(events, key=lambda e: (e.period, e.match_time_seconds, e.event_id))
    items = []
    for event in events:
        if event.event_type not in ('goal', 'shot', 'card', 'corner', 'save'):
            continue
        actor = players.get(event.player_id, teams.get(event.team_id, 'A player'))
        action = {'goal': 'scores', 'shot': 'takes a shot', 'card': 'receives a card',
                  'corner': 'wins a corner', 'save': 'makes a save'}[event.event_type]
        detail = f' ({event.outcome})' if event.outcome and event.event_type == 'card' else ''
        facts = ' · '.join(str(v) for v in (event.event_type, event.body_part, event.outcome) if v)
        text = {
            'simple': f'{actor} {action}{detail}.',
            'casual': f"{teams.get(event.team_id, 'Match update')}: {actor} {action}{detail}.",
            'experienced': f'{actor} {action}{detail}. Recorded outcome: {event.outcome or "not specified"}.',
            'analytical': f'{actor} — {facts}.',
        }
        # Framing and approved-stat order belong to the upstream fixture. The
        # backend selects these messages without rewriting or doing calculations.
        for team in [*teams, 'neutral']:
            prefix = team if team != 'neutral' else 'all'
            for style, order in STAT_ORDER.items():
                items.append({'id': f'{event.event_id}:{event.revision}:{team}:{style}',
                    'text': text[style], 'clock_seconds': event.match_time_seconds, 'period': event.period,
                    'buckets': [f'{team}:{style}'],
                    'stat_ids': [f'{prefix}:{kind}' for kind in order], 'synthetic': True})
    return {'items': items[-480:], 'events': [e.model_dump(mode='json') for e in events[-30:]]}
