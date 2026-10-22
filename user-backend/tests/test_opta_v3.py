"""Opta-style v3 canonical events (MatchEvent v2: clock and ticker) and SPADL capability gates."""
import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from benchmarks.doubles.events import OptaInspiredAdapter
from backend.adapters.feed_reference import FeedReference
from backend.adapters.match_reference import data_reference
from benchmarks.doubles.recording import FixtureEventSource
from backend.agents.models import Goal
from backend.models.actions import ActionType, SpadlAction
from backend.models.events import Event, EventType
from backend.services.filter_engine import FilterEngine
from backend.models.questions import MatchSnapshot
from backend.services.observed import observed
from backend.agents.measurement_support import measurement_support
from backend.services.rule_availability import UNDECLARED, supported_rule, unsupported_reason

SPEC = json.loads((Path(__file__).parents[1] / 'fixtures/filter-lab.json').read_text())
V3_TYPES = ('clearance', 'dispossessed', 'blocked_pass', 'aerial', 'take_on', 'challenge', 'ball_recovery',
            'out', 'corner_awarded', 'keeper_pickup', 'punch', 'offside_provoked', 'error', 'ball_touch',
            'save', 'tackle', 'interception')
CAPABILITIES = {'supported_event_types': [*get_args(EventType)], 'shot_outcomes': True,
                'distance_event_types': ['pass', 'clearance'], 'coordinates': 'opta_0_100',
                'clock': 'broadcast_with_stoppage', 'restart_events': 'taken',
                'body_parts': False, 'body_part_event_types': ['pass', 'shot', 'goal']}


def raw(sequence, kind='pass', period=1, minute=0, second=0, **changes):
    return {'eventId': f'v{sequence}', 'matchId': SPEC['match_id'], 'revision': 1, 'sequence': sequence,
            'typeName': kind, 'teamId': 'riverton', 'playerId': 'ashworth', 'periodId': period,
            'timeMin': minute, 'timeSec': second, 'x': 41.5, 'y': 63.0, 'possessionId': sequence,
            'qualifiers': [], 'outcome': None, 'videoSeconds': float(sequence), 'synthetic': True} | changes


def v3_recording(events, football=5400):
    last = events[-1]['videoSeconds']
    return {**{k: SPEC[k] for k in ('synthetic', 'match_id', 'teams', 'players')}, 'events': events,
            'capabilities': CAPABILITIES,
            'provenance': {'source': 'Google Research Football instrumented native runtime'},
            'playback': {'duration_seconds': last + 25, 'football_duration_seconds': football,
                         'halftime_seconds': last / 2}}


def source(events, **kwargs):
    return FixtureEventSource(content=json.dumps(v3_recording(events, **kwargs)).encode())


def test_v3_event_keeps_location_possession_video_and_qualifiers():
    pass_qualifiers = [{'type': 'bodyPart', 'value': 'right_foot'}, {'type': 'distanceMetres', 'value': 34.2},
                       {'type': 'endX', 'value': 70.1}, {'type': 'endY', 'value': 12.0},
                       {'type': 'angle', 'value': 0.4}, {'type': 'longBall', 'value': True},
                       {'type': 'cross', 'value': False}, {'type': 'unknownVendorKey', 'value': 1}]
    event = OptaInspiredAdapter().adapt(raw(7, qualifiers=pass_qualifiers, outcome='success'))
    assert (event.x, event.y, event.possession_id, event.video_seconds, event.sequence) == (41.5, 63.0, 7, 7.0, 7)
    assert event.body_part == 'right_foot' and event.distance_metres == 34.2
    assert event.qualifiers['longBall'] is True and event.qualifiers['endX'] == 70.1
    assert 'unknownVendorKey' not in event.qualifiers


@pytest.mark.parametrize('kind', V3_TYPES)
def test_v3_categories_are_accepted_and_defined(kind):
    # Canonical categories still validate for the clock and ticker; agents read SPADL meanings instead.
    event = OptaInspiredAdapter().adapt(raw(1, kind, outcome='success'))
    assert event.event_type == kind


def action(**changes):
    base = {'match_id': SPEC['match_id'], 'action_id': 0, 'period': 1, 'match_time_seconds': 600, 'team_id': 'riverton',
            'player_id': 'ashworth', 'action_type': 'shot', 'result': 'fail', 'bodypart': 'foot', 'start_x': 90.0,
            'start_y': 34.0, 'end_x': 105.0, 'end_y': 34.0, 'start_zone': 'opp_box', 'end_zone': 'opp_box', 'seq': 1,
            'final_seq': 1, 'source_type_id': 15}
    return SpadlAction(**base | changes)


@pytest.mark.parametrize('outcome, changes', [('off_target', {'source_type_id': 13}), ('post', {'source_type_id': 14}),
                                               ('saved', {}), ('blocked', {'end_x': 95.0}),
                                               ('goal', {'result': 'success', 'source_type_id': 16})])
def test_shot_outcome_filters_follow_the_catalogue(outcome, changes):
    shot = action(**changes)
    goal = Goal(description='shots', action_types=('shot', 'shot_penalty', 'shot_freekick'), shot_outcomes=(outcome,))
    rule = goal.target_rule(SPEC['match_id'])
    assert shot.shot_outcome == outcome and rule.matches(shot) and supported_rule(rule, CAPABILITIES)
    assert not supported_rule(rule, CAPABILITIES | {'shot_outcomes': False})


@pytest.mark.parametrize('changes', [
    {'x': 111.0}, {'y': -10.5}, {'x': float('nan')}, {'possessionId': -1}, {'possessionId': 1.5},
    {'x': '50'}, {'sourceShotEventId': 'v1'},
])
def test_v3_fields_are_strictly_typed(changes):
    with pytest.raises(ValidationError):
        OptaInspiredAdapter().adapt(raw(1) | changes)


def test_teamless_records_have_null_coordinates():
    event = OptaInspiredAdapter().adapt(raw(1, 'period_start', teamId=None, playerId=None, x=None, y=None,
                                            possessionId=None))
    assert (event.x, event.y, event.possession_id) == (None, None, None)


@pytest.mark.parametrize('row', [
    {},
    {'x': 12.5, 'y': 80.0, 'video_seconds': 3.5, 'possession_id': 4, 'sequence': 9,
     'qualifiers': {'endX': 40.0, 'longBall': True}},
    {'x': 12.5, 'y': None, 'videoSeconds': 3.5, 'possessionId': 4},
])
def test_upstream_history_rows_accept_optional_v3_context(row):
    base = {'event_id': 'e1', 'match_id': 'm', 'revision': 1, 'event_type': 'clearance', 'team_id': 'a',
            'player_id': None, 'body_part': None, 'period': 1, 'match_time_seconds': 2900, 'outcome': None,
            'distance_metres': 30.0, 'deleted': False}
    event = Event.model_validate(base | row)
    assert event.event_type == 'clearance'
    if 'x' in row:
        assert (event.x, event.video_seconds, event.possession_id) == (12.5, 3.5, 4)
    with pytest.raises(ValidationError):
        Event.model_validate(base | row | {'unexpected': 1})


def test_redelivery_at_another_time_is_not_a_conflict():
    adapter = OptaInspiredAdapter()
    first = adapter.adapt(raw(1))
    assert first.same_content(adapter.adapt(raw(1) | {'sequence': 5, 'videoSeconds': 9.0}))
    assert not first.same_content(adapter.adapt(raw(1) | {'x': 10.0}))
    engine = FilterEngine()  # Final SPADL actions: a repeat is ignored, different content is refused.
    engine.ingest(action())
    assert engine.ingest(action()) == []
    with pytest.raises(ValueError, match='Conflicting'):
        engine.ingest(action(end_x=100.0))


def stoppage_events():
    return [raw(1, 'period_start', teamId=None, playerId=None, x=None, y=None, possessionId=None),
            raw(2, minute=47, second=30),                         # first-half stoppage: 2850 s
            raw(3, 'period_end', minute=48, second=24, teamId=None, playerId=None, x=None, y=None),
            raw(4, 'period_start', 2, 45, teamId=None, playerId=None, x=None, y=None),  # 2700 s
            raw(5, period=2, minute=46),
            raw(6, period=2, minute=94, second=10),                # second-half stoppage: 5650 s
            raw(7, 'period_end', 2, 94, 41, teamId=None, playerId=None, x=None, y=None)]


def test_stoppage_time_orders_by_period_not_clock_seconds():
    recording = source(stoppage_events())
    # Second half restarts at 45:00, earlier on the clock than first-half stoppage.
    snapshot = MatchSnapshot.at('m', 4, recording.events[3])
    assert (snapshot.id, snapshot.period, snapshot.clock_seconds) == ('m:4', 2, 2700)
    snapshot = MatchSnapshot.at('m', 3, recording.events[2])
    assert (snapshot.period, snapshot.clock_seconds) == (1, 2904)
    ordered = [e.event_id for e in observed(recording.history(6))]
    assert ordered == ['v1', 'v2', 'v3', 'v4', 'v5', 'v6']


def test_spadl_reference_declares_location_filters_from_capabilities():
    reference = source(stoppage_events()).data_reference()
    assert reference['contract_id'] == 'spadl-v1'
    assert {'start_x', 'end_y', 'start_zone', 'end_zone'} <= set(reference['fields'])
    assert reference['availability']['locations'] and reference['availability']['shot_outcomes']
    assert any('start/end x/y' in text for text in reference['guarantees'])
    assert 'supported_event_types' not in reference['capabilities']  # The provider's vocabulary stays out.
    complete = FixtureEventSource().data_reference()['availability']  # The double declares the full test contract.
    assert complete['recorded_bodyparts'] and complete['shot_outcomes'] and complete['locations']


def test_undeclared_capabilities_are_unknown_not_complete():
    """An MA1 without capabilities: every rule needing body parts, shot outcomes or locations is refused."""
    reference = data_reference(None)
    assert 'availability' not in reference and measurement_support(reference) == {'declared': False}
    def rule(**goal):
        return Goal(description='x', **goal).target_rule(SPEC['match_id'])
    assert unsupported_reason(rule(operation='count', action_types=('pass',)), None) is None
    for gated in (rule(operation='count', action_types=('shot',), bodyparts=('head',)),
                  rule(operation='count', action_types=('pass',), start_zones=('final_third',)),
                  rule(operation='count', action_types=('shot',), coverage='recorded', bodyparts=('head',))):
        assert unsupported_reason(gated, None) == UNDECLARED


def test_profile_parity_with_spadl_action_model():
    reference = FeedReference.load().describe()
    assert reference['contract_id'] == 'spadl-v1'
    assert set(reference['fields']) == set(SpadlAction.model_fields)
    assert set(reference['events']) == set(get_args(ActionType))


def test_v3_capability_gates():
    def rule(**goal):
        return Goal(description='x', **goal).target_rule(SPEC['match_id'])
    distance = rule(operation='sum', sum_field='distance_metres', action_types=('clearance',))
    assert supported_rule(distance, CAPABILITIES)
    older = CAPABILITIES | {'coordinates': None, 'shot_outcomes': False, 'body_part_event_types': ['pass']}
    assert not supported_rule(distance, older)
    assert not supported_rule(rule(action_types=('pass',), end_zones=('opp_box',)), older)
    assert not supported_rule(rule(action_types=('shot',), shot_outcomes=('post',)), older)
    assert supported_rule(rule(action_types=('pass', 'cross'), bodyparts=('head',)), older)
    assert not supported_rule(rule(action_types=('shot',), bodyparts=('head',)), older)
    assert supported_rule(rule(bodyparts=('head',), coverage='recorded'), older)
    assert data_reference(older)['availability']['complete_bodypart_types'] == [
        'corner_crossed', 'corner_short', 'cross', 'freekick_crossed', 'freekick_short', 'goalkick', 'pass', 'throw_in']


def test_full_match_recording_exceeds_old_size_and_count_caps():
    events = [raw(i, 'touch', period=1 if i <= 12000 else 2, minute=min(i // 300, 94),
                  videoSeconds=i * 0.25) for i in range(1, 21001)]
    content = json.dumps(v3_recording(events)).encode()
    assert len(content) > 2 * 1024 * 1024
    recording = FixtureEventSource(content=content)
    assert len(recording.events) == 21000
    assert recording.playback_duration == events[-1]['videoSeconds'] + 25
