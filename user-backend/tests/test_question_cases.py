"""The opt-in question cases stay bound to the shipped recording: recompute every expected value."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from benchmarks.evaluate_questions import check

ROOT = Path(__file__).parents[2]
SUITE = json.loads((Path(__file__).parents[1] / 'benchmarks/question_cases.json').read_text())


def spadl_actions():
    """The recording's SPADL actions through ETL's converter (an independent count, not the rule engine)."""
    import sys
    sys.path.insert(0, str(ROOT / 'etl'))
    from reference import spadl
    from benchmarks.doubles.spadl import ma3_rows
    return spadl, spadl.actions(ma3_rows(ROOT / SUITE['recording']), 'chelsea')


def test_question_cases_match_the_shipped_recording():
    content = (ROOT / SUITE['recording']).read_bytes()
    assert hashlib.sha256(content).hexdigest() == SUITE['recording_hash']
    recording = json.loads(content)
    assert recording['match_id'] == SUITE['match_id']
    spadl, actions = spadl_actions()

    def count(types=None, **fields):
        return sum((types is None or a['typeName'] in types) and all(a[k] == v for k, v in fields.items())
                   for a in actions)

    owned = Counter()
    for sample in recording['possession_samples']:
        owned[sample['team_id']] += sample['duration_seconds']
    share = {team: round(100 * seconds / sum(owned.values()), 1) for team, seconds in owned.items()}
    passes = spadl.PASS_FAMILY
    completed = count(passes, teamId='chelsea', periodId=2, resultName='success')
    expected = {
        'standard': [['chelsea:shots', count(spadl.SHOT_FAMILY, teamId='chelsea')]],
        'standard-restarts': [['manutd:corners', count({'corner_crossed', 'corner_short'}, teamId='manutd')]],
        'possession': [['chelsea:possession', share['chelsea']], ['manutd:possession', share['manutd']]],
        'custom': count(passes, teamId='chelsea', periodId=2),
        'followup': count(passes, teamId='manutd', periodId=2),
        'composite': round(100 * completed / count(passes, teamId='chelsea', periodId=2), 3),
        'clarification-answer': count(spadl.SHOT_FAMILY, playerId='chelsea-9'),
        'keeper-saves': count({'keeper_save'}, playerId='manutd-0', fromShotOffTarget=False, defensiveBlock=False),
        'player-touches': count(set(spadl.ACTIONTYPES) - {'dribble', 'non_action'}, playerId='chelsea-1'),
    }
    cases = {case['id']: case for case in SUITE['cases']}
    for identifier, value in expected.items():
        assert cases[identifier].get('offers', cases[identifier].get('offer_value')) == value, identifier
    assert next(p['name'] for p in recording['players'] if p['id'] == 'chelsea-9') == cases['clarification-answer']['prompt']
    leaders = Counter(a['playerId'] for a in actions if a['typeName'] in passes and a['resultName'] == 'success')
    assert cases['leader-completed-passes']['leaders'] == [list(leaders.most_common(1)[0])]


def test_possession_case_requires_both_etl_rows_not_a_count():
    case = next(case for case in SUITE['cases'] if case['id'] == 'possession')
    snapshot = {'match_id': 'chelsea-united-1a2b3c4d'}
    split = {'status': 'answer', 'snapshot': snapshot, 'standard_stat_id': 'all:possession',
             'offers': [{'kind': 'standard', 'standard_stat_id': i, 'value': v} for i, v in case['offers']]}
    assert all(check(case, split, 'chelsea-united-1a2b3c4d').values())
    count = {'status': 'answer', 'snapshot': snapshot, 'offers': [{'rule': {}, 'value': 11388}]}
    assert not all(check(case, count, 'chelsea-united-1a2b3c4d').values())


def test_timed_question_cases_match_the_recording_prefix():
    """Mid-match cases (benchmarks/question_inprocess.py) recompute from the snapshot's final actions."""
    from benchmarks.question_inprocess import cursor_at
    from benchmarks.doubles.recording import FixtureEventSource
    from benchmarks.doubles.spadl import ma3_rows
    recording = json.loads((ROOT / SUITE['recording']).read_bytes())
    events = FixtureEventSource(ROOT / SUITE['recording']).events
    spadl, actions = spadl_actions()
    raw = ma3_rows(ROOT / SUITE['recording'])
    for case in (case for case in SUITE['cases'] if 'at' in case):
        seq = cursor_at(events, case['at'])
        video = (recording['playback']['duration_seconds'] if seq == len(events)
                 else max(e['videoSeconds'] for e in recording['events'][:seq]))
        owned = Counter()
        for sample in recording['possession_samples']:
            if sample['video_seconds'] <= video:
                owned[sample['team_id']] += sample['duration_seconds']
        final = [a for a in actions if a['finalSeq'] <= seq]

        def value(stat):
            team, kind = stat.split(':')
            rows = [a for a in final if a['teamId'] == team]
            shots = [a for a in rows if a['typeName'] in spadl.SHOT_FAMILY]
            if kind == 'possession':
                return round(100 * owned[team] / sum(owned.values()), 1)
            if kind == 'cards':
                return sum(m['typeId'] == 17 and m['contestantId'] == team and m['eventSeq'] <= seq for m in raw)
            if kind == 'goals':
                return sum(a['resultName'] == 'success' for a in shots) + sum(
                    a['resultName'] == 'owngoal' for a in final if a['teamId'] != team)
            if kind == 'shots_on_target':  # Goals plus saved attempts ending on the goal line (team-relative).
                return sum(a['resultName'] == 'success' or a['sourceTypeId'] == 15 and (
                    a['endX'] if team == 'chelsea' else 105 - a['endX']) >= 105 for a in shots)
            return len(shots) if kind == 'shots' else sum(a['typeName'] in ('corner_crossed', 'corner_short') for a in rows)
        for stat, expected in case.get('offers', []):
            assert value(stat) == expected, (case['id'], stat)
