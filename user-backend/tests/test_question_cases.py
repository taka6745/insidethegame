"""The opt-in question cases stay bound to the shipped recording: recompute every expected value."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from benchmarks.evaluate_questions import check

ROOT = Path(__file__).parents[2]
SUITE = json.loads((Path(__file__).parents[1] / 'benchmarks/question_cases.json').read_text())


def test_question_cases_match_the_shipped_recording():
    content = (ROOT / SUITE['recording']).read_bytes()
    assert hashlib.sha256(content).hexdigest() == SUITE['recording_hash']
    recording = json.loads(content)
    assert recording['match_id'] == SUITE['match_id']
    events = recording['events']
    assert all(e['revision'] == 1 and not e.get('deleted') for e in events)  # No corrections to resolve.

    def count(kinds, **fields):
        return sum(e['typeName'] in kinds and all(e[k] == v for k, v in fields.items()) for e in events)

    owned = Counter()
    for sample in recording['possession_samples']:
        owned[sample['team_id']] += sample['duration_seconds']
    share = {team: round(100 * seconds / sum(owned.values()), 1) for team, seconds in owned.items()}
    completed = count({'pass'}, teamId='chelsea', periodId=2, outcome='success')
    resolved = completed + count({'pass'}, teamId='chelsea', periodId=2, outcome='failure')
    expected = {
        'standard': [['chelsea:shots', count({'shot', 'goal'}, teamId='chelsea')]],
        'standard-restarts': [['manutd:corners', count({'corner'}, teamId='manutd')]],
        'possession': [['chelsea:possession', share['chelsea']], ['manutd:possession', share['manutd']]],
        'custom': count({'pass'}, teamId='chelsea', periodId=2),
        'followup': count({'pass'}, teamId='manutd', periodId=2),
        'composite': round(100 * completed / resolved, 3),
        'clarification-answer': count({'shot', 'goal'}, playerId='chelsea-6'),
    }
    cases = {case['id']: case for case in SUITE['cases']}
    for identifier, value in expected.items():
        assert cases[identifier].get('offers', cases[identifier].get('offer_value')) == value, identifier
    assert next(p['name'] for p in recording['players'] if p['id'] == 'chelsea-6') == cases['clarification-answer']['prompt']


def test_possession_case_requires_both_etl_rows_not_a_count():
    case = next(case for case in SUITE['cases'] if case['id'] == 'possession')
    snapshot = {'recording_hash': SUITE['recording_hash']}
    split = {'status': 'answer', 'snapshot': snapshot, 'standard_stat_id': 'all:possession',
             'offers': [{'kind': 'standard', 'standard_stat_id': i, 'value': v} for i, v in case['offers']]}
    assert all(check(case, split, SUITE).values())
    count = {'status': 'answer', 'snapshot': snapshot, 'offers': [{'rule': {}, 'value': 11388}]}
    assert not all(check(case, count, SUITE).values())
