"""Small synthetic broadcast-clock match and fixtures in the v2 schema. Not real data."""
import copy
import hashlib
import json

from narrative_demo.models.clock import minute_id
from narrative_demo.models.fixtures import BUCKETS
from narrative_demo.models.snapshots import SnapshotInput
from tools.bind_commentary import bind, match_minutes

HASH = 'a' * 64
TEAMS = [{'id': 'CHE', 'name': 'Chelsea'}, {'id': 'MUN', 'name': 'Manchester United'}]


def event(identifier, seconds, kind='pass', period=None, **extra):
    return {'event_id': identifier, 'match_id': 'match', 'revision': 1, 'event_type': kind,
            'team_id': 'CHE', 'player_id': 'palmer', 'match_time_seconds': seconds,
            'period': period or (1 if seconds < 2700 else 2), 'deleted': False, **extra}


# Delivery order. First-half stoppage (45+1, 45+2) precedes the second half's 45:00.
MATCH = [
    (event('p1-start', 0, 'period_start', 1), 0),
    (event('pass-1', 30), 30),
    (event('goal-1', 100, 'goal'), 100),
    (event('pass-2', 2690), 2690),
    (event('card-1', 2720, 'card', 1, team_id='MUN', player_id='casemiro'), 2720),
    (event('shot-1', 2770, 'shot', 1, outcome='saved'), 2770),
    (event('p1-end', 2790, 'period_end', 1, team_id=None, player_id=None), 2790),
    (event('p2-start', 2700, 'period_start', 2, team_id=None, player_id=None), 3700),
    (event('shot-2', 2730, 'shot', 2, team_id='MUN', player_id='fernandes', outcome='off_target'), 3730),
    (event('goal-2', 2765, 'goal', 2, team_id='MUN', player_id='fernandes'), 3765),
    (event('p2-end', 2780, 'period_end', 2, team_id=None, player_id=None), 3780),
]
EVENTS = [row for row, _ in MATCH]
TIMES = [seconds for _, seconds in MATCH]


def payload(events=None, clock=None, period=None, recording_hash=HASH):
    events = copy.deepcopy(EVENTS if events is None else events)
    last = events[-1] if events else {'match_time_seconds': 0, 'period': 1}
    body = {'snapshot': {'id': 'pending', 'run_id': 'run', 'match_id': 'match', 'recording_hash': recording_hash,
                         'cursor': len(events), 'clock_seconds': last['match_time_seconds'] if clock is None else clock,
                         'period': period or last['period'], 'captured_at': 'now'},
            'events': events, 'teams': TEAMS, 'players': [{'id': 'palmer', 'name': 'Cole Palmer'}],
            'data_reference': {}}
    raw = copy.deepcopy(body)
    raw['snapshot'].pop('id')
    raw['snapshot'].pop('captured_at')
    body['snapshot']['id'] = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return SnapshotInput.model_validate(body)


def at(cursor, **change):
    return payload(EVENTS[:cursor], **change)


def text(events=EVENTS):
    minutes = [minute_id(*key) for key in match_minutes(events)]
    first_half = [m for m in minutes if m.startswith('p1-')]
    return {
        'provenance': {'authored_by': 'test', 'synthetic': True},
        'minutes': {m: {'recap': f'Recap {m}.', 'narratives': {b: f'{b} on {m}.' for b in BUCKETS}} for m in minutes},
        'tiers': [
            {'id': 'p1-five-1', 'tier': 'five-minute', 'child_ids': first_half[:5], 'summary': 'Opening five.'},
            {'id': 'p1-half', 'tier': 'half', 'child_ids': ['p1-five-1', *first_half[5:]], 'summary': 'First half.'},
            {'id': 'p2-half', 'tier': 'half', 'child_ids': ['p2-m46', 'p2-m47'], 'summary': 'Second half.'},
        ],
        'key_moments': [
            {'id': 'km-opener', 'rank': 2, 'title': 'Opener', 'summary': 'Palmer scores.',
             'event_ids': ['goal-1'], 'start_video_seconds': 95, 'end_video_seconds': 110},
            {'id': 'km-late', 'rank': 1, 'title': 'Late reply', 'summary': 'Fernandes scores.',
             'event_ids': ['shot-2', 'goal-2'], 'start_video_seconds': 3725, 'end_video_seconds': 3770},
        ],
    }


def export(events=EVENTS, times=TIMES):
    return {'recording_hash': HASH, 'events': events, 'video_times': times, 'teams': TEAMS}


def fixture_file(tmp_path, document=None):
    path = tmp_path / 'narratives.json'
    path.write_text(json.dumps(document or bind(text(), export(), HASH)))
    return path
