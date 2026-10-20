"""Prewritten audience narratives for the two bundled synthetic recordings.

This is a removable upstream fixture, not a narrative-generation implementation.
Unrecognised or edited recordings receive no scripted commentary.
"""
import json
from functools import lru_cache
from pathlib import Path

from .adapters.replay_source import FixtureEventSource

STAT_ORDER = {
    'simple': ('goals', 'cards', 'shots', 'corners', 'passes'),
    'casual': ('goals', 'shots', 'corners', 'cards', 'passes'),
    'experienced': ('shots', 'passes', 'cards', 'corners', 'goals'),
    'analytical': ('shots', 'corners', 'passes', 'goals', 'cards'),
}
FIXTURES = Path(__file__).parents[1] / 'fixtures'


@lru_cache(maxsize=1)
def _recordings():
    sources = [FixtureEventSource(FIXTURES / name)
               for name in ('product-demo.json', 'filter-lab.json')]
    return {source.fingerprint: source for source in sources}


@lru_cache(maxsize=1)
def _moments():
    return json.loads((FIXTURES / 'viewer-narratives.json').read_text())['moments']


def viewer_narratives(payload, events):
    result = {'items': [], 'events': [e.model_dump(mode='json') for e in events[-30:]]}
    source = _recordings().get(payload.snapshot.recording_hash)
    if (source is None or payload.snapshot.match_id != source.match_id
            or payload.events != list(source.history(len(payload.events)))
            or payload.teams != source.spec['teams'] or payload.players != source.spec['players']):
        return result

    teams = payload.teams
    players = {p['id']: p['name'] for p in payload.players}
    original = {e.event_id: e for e in source.events}
    names = {'home': teams[0]['name'], 'away': teams[1]['name']}
    for role, event_id in [('away_creator', 'e2'), ('away_forward', 'e14'),
                           ('home_scorer', 'e22'), ('home_defender', 'e20')]:
        names[role] = players[original[event_id].player_id]
    observed = {event.event_id: event for event in events}
    for moment in _moments():
        if (not set(moment['required_event_ids']).issubset(observed)
                or set(moment.get('absent_event_ids', ())).intersection(observed)):
            continue
        trigger = observed.get(moment['trigger_event_id'])
        if trigger is None:
            continue
        for perspective, team in [('home', teams[0]['id']), ('away', teams[1]['id']), ('neutral', 'neutral')]:
            prefix = team if team != 'neutral' else 'all'
            for style, order in STAT_ORDER.items():
                result['items'].append({
                    'id': f"fixture:{source.match_id}:{moment['id']}:{team}:{style}",
                    'text': moment['texts'][perspective][style].format(**names),
                    'clock_seconds': trigger.match_time_seconds, 'period': trigger.period,
                    'buckets': [f'{team}:{style}'],
                    'stat_ids': [f'{prefix}:{kind}' for kind in order], 'synthetic': True,
                })
    return result
