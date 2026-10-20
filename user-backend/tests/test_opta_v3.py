"""Opta-style v3 contract: coordinates, new categories and the broadcast clock."""
import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from backend.adapters.events import OptaInspiredAdapter
from backend.adapters.replay_source import FixtureEventSource
from backend.agents.models import Goal
from backend.fake_question_data import observed_events, snapshot_id
from backend.models.events import DETAIL_FIELDS, Event, EventType
from backend.services.filter_engine import FilterEngine
from backend.services.question_snapshot import build_snapshot
from backend.services.rule_availability import supported_rule

SPEC = json.loads((Path(__file__).parents[1] / 'fixtures/filter-lab.json').read_text())
V3_TYPES = ('clearance', 'dispossessed', 'blocked_pass', 'aerial', 'take_on', 'challenge', 'ball_recovery',
            'out', 'corner_awarded', 'keeper_pickup', 'punch', 'offside_provoked', 'error', 'ball_touch',
            'save', 'tackle', 'interception')
CAPABILITIES = {'supported_event_types': [*get_args(EventType)], 'shot_outcomes': True,
                'distance_event_types': ['pass', 'clearance'], 'coordinates': 'opta_0_100',
                'clock': 'broadcast_with_stoppage', 'restart_events': 'taken'}


def raw(sequence, kind='pass', period=1, minute=0, second=0, **changes):
    return {'eventId': f'v{sequence}', 'matchId': SPEC['match_id'], 'revision': 1, 'sequence': sequence,
            'typeName': kind, 'teamId': 'chelsea', 'playerId': 'palmer', 'periodId': period,
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
    event = OptaInspiredAdapter().adapt(raw(1, kind, outcome='success'))
    assert event.event_type == kind
    assert OptaInspiredAdapter().data_reference()['events'][kind]


@pytest.mark.parametrize('outcome', ['off_target', 'post', 'saved', 'blocked'])
def test_shot_outcomes_and_shot_qualifiers(outcome):
    qualifiers = [{'type': 'situation', 'value': 'regular_play'}, {'type': 'bigChance', 'value': True},
                  {'type': 'goalMouthY', 'value': 53.6}, {'type': 'goalMouthZ', 'value': 8.5},
                  {'type': 'shotOutcome', 'value': outcome}, {'type': 'assistEventId', 'value': 'v1'}]
    event = OptaInspiredAdapter().adapt(raw(2, 'shot', outcome=outcome, qualifiers=qualifiers))
    goal = Goal(description='shots', event_types=('shot',), outcome=outcome)
    rule = goal.target_rule(SPEC['match_id'])
    assert rule.matches(event) and supported_rule(rule, CAPABILITIES)


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
    adapter, engine = OptaInspiredAdapter(), FilterEngine()
    first = adapter.adapt(raw(1))
    again = adapter.adapt(raw(1) | {'sequence': 5, 'videoSeconds': 9.0})
    engine.ingest(first)
    engine.ingest(again)
    with pytest.raises(ValueError, match='Conflicting'):
        engine.ingest(adapter.adapt(raw(1) | {'x': 10.0}))


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
    snapshot = build_snapshot(recording, 'run', 4).snapshot
    assert (snapshot.period, snapshot.clock_seconds) == (2, 2700)
    snapshot = build_snapshot(recording, 'run', 3).snapshot
    assert (snapshot.period, snapshot.clock_seconds) == (1, 2904)
    ordered = [e.event_id for e in observed_events(recording.history(6))]
    assert ordered == ['v1', 'v2', 'v3', 'v4', 'v5', 'v6']


def test_finished_clock_never_rewinds_from_stoppage():
    recording = source(stoppage_events())
    snapshot = build_snapshot(recording, 'run', len(recording.events), finished=True).snapshot
    assert snapshot.clock_seconds > recording.spec['playback']['football_duration_seconds']
    assert (snapshot.period, snapshot.clock_seconds) == (2, 94 * 60 + 41)


def test_finished_clock_reaches_full_time_when_recording_stops_early():
    recording = source(stoppage_events()[:5])
    snapshot = build_snapshot(recording, 'run', len(recording.events), finished=True).snapshot
    assert (snapshot.period, snapshot.clock_seconds) == (2, recording.spec['playback']['football_duration_seconds'])


def test_v3_reference_states_coordinates_are_context_not_filters():
    reference = source(stoppage_events()).data_reference()
    assert reference['contract_id'] == 'synthetic-grf-opta-v3'
    assert {'x', 'y', 'possession_id', 'video_seconds', 'qualifiers'} <= set(reference['fields'])
    assert not any('no x/y coordinates' in text for text in reference['unavailable'])
    assert any('not filterable' in text for text in reference['guarantees'])
    assert 'unknown scorer' not in reference['events']['goal']
    older = FixtureEventSource().data_reference()
    assert any('no x/y coordinates' in text for text in older['unavailable'])


def test_profile_parity_with_canonical_event_schema():
    reference = OptaInspiredAdapter().data_reference()
    assert reference['contract_id'] == 'synthetic-opta-inspired-v2'
    assert set(reference['fields']) == set(Event.model_fields)
    assert set(reference['events']) == set(get_args(EventType))


def test_v3_capability_gates():
    def rule(**goal):
        return Goal(description='x', **goal).target_rule(SPEC['match_id'])
    assert supported_rule(rule(operation='sum', sum_field='distance_metres', event_types=('clearance',)), CAPABILITIES)
    older = CAPABILITIES | {'supported_event_types': ['pass', 'shot', 'goal'], 'shot_outcomes': False,
                            'distance_event_types': ['pass']}
    assert not supported_rule(rule(event_types=('aerial',)), older)
    assert not supported_rule(rule(event_types=('shot',), outcome='post'), older)
    assert not supported_rule(rule(operation='sum', sum_field='distance_metres', event_types=('clearance',)), older)


def test_full_match_recording_exceeds_old_size_and_count_caps():
    events = [raw(i, 'touch', period=1 if i <= 12000 else 2, minute=min(i // 300, 94),
                  videoSeconds=i * 0.25) for i in range(1, 21001)]
    content = json.dumps(v3_recording(events)).encode()
    assert len(content) > 2 * 1024 * 1024
    recording = FixtureEventSource(content=content)
    assert len(recording.events) == 21000
    assert recording.playback_duration == events[-1]['videoSeconds'] + 25


def test_snapshot_identity_matches_without_optional_v3_context():
    # ETL hashes the same identity, so producers that omit v3 context name the same prefix.
    payload = build_snapshot(source(stoppage_events()), 'run', 5)
    bare = payload.model_copy(update={'events': [
        e.model_copy(update={k: {} if k == 'qualifiers' else None for k in DETAIL_FIELDS}) for e in payload.events]})
    assert snapshot_id(bare) == payload.snapshot.id
    changed = payload.model_copy(update={'events': [*payload.events[:-1],
                                                    payload.events[-1].model_copy(update={'period': 1})]})
    assert snapshot_id(changed) != payload.snapshot.id
