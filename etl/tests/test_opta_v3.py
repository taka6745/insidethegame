"""Opta-style v3 contract: derived events, location, broadcast clock and new standard stats."""
import json
import typing

import pytest
from fastapi.testclient import TestClient

from demo_etl.adapters.recording import RecordingSource, adapt_event
from demo_etl.models.snapshot import EventType, QualifierType
from demo_etl.routes.http import create_app
from demo_etl.services.match import MatchService
from demo_etl.services.statistics import observed, project
from test_etl import MemoryHistory, MemoryStats, owned_payload, payload, values

V3_TYPES = ['clearance', 'dispossessed', 'blocked_pass', 'aerial', 'take_on', 'challenge', 'ball_recovery', 'out',
            'corner_awarded', 'keeper_pickup', 'punch', 'offside_provoked', 'error', 'ball_touch', 'save', 'tackle',
            'interception']
QUALIFIERS = [('endX', 71.5), ('endY', 40.0), ('angle', 0.3), ('longBall', True), ('cross', True),
              ('chipped', True), ('switchOfPlay', True), ('offsidePass', True), ('situation', 'open_play'),
              ('assistEventId', 'e-1'), ('bigChance', True), ('goalMouthY', 48.2), ('goalMouthZ', 12.0),
              ('shotOutcome', 'saved'), ('saveType', 'caught'), ('defensiveBlock', True), ('penaltyAwarded', True),
              ('cardReason', 'foul'), ('leadsTo', 'shot'), ('relatedEventId', 'e-2'), ('woodwork', True)]


def raw(kind='pass', sequence=1, period=1, minute=20, second=0, **changes):
    return {'eventId': f'e{sequence}', 'matchId': 'match', 'revision': 1, 'sequence': sequence, 'typeName': kind,
            'teamId': 'chelsea', 'playerId': 'palmer', 'periodId': period, 'timeMin': minute, 'timeSec': second,
            'x': 60.5, 'y': 12.25, 'qualifiers': [], 'outcome': None, 'videoSeconds': float(sequence),
            'possessionId': 3, 'synthetic': True, **changes}


def rows(*specs):
    return [adapt_event(raw(kind, index, outcome=outcome)) for index, (kind, outcome) in enumerate(specs, 1)]


@pytest.mark.parametrize('kind', V3_TYPES)
def test_every_v3_type_is_accepted(kind):
    assert adapt_event(raw(kind)).event_type == kind


def test_contract_lists_are_explicit():
    assert set(V3_TYPES) <= set(typing.get_args(EventType))
    assert {name for name, _ in QUALIFIERS} <= set(typing.get_args(QualifierType))


def test_location_video_possession_and_all_qualifiers_are_kept():
    qualifiers = [{'type': name, 'value': value} for name, value in QUALIFIERS] + [
        {'type': 'bodyPart', 'value': 'head'}, {'type': 'distanceMetres', 'value': 34.5}]
    event = adapt_event(raw('pass', 7, qualifiers=qualifiers))
    assert (event.x, event.y, event.possession_id, event.video_seconds, event.sequence) == (60.5, 12.25, 3, 7.0, 7)
    assert event.qualifiers == {**dict(QUALIFIERS), 'bodyPart': 'head', 'distanceMetres': 34.5}
    assert event.body_part == 'head' and event.distance_metres == 34.5
    period = adapt_event(raw('period_start', x=None, y=None, possessionId=None, teamId=None, playerId=None))
    assert period.x is None and period.possession_id is None


@pytest.mark.parametrize('changes', [
    {'qualifiers': [{'type': 'xG', 'value': 0.4}]},
    {'qualifiers': [{'type': 'endX', 'value': {'nested': 1}}]},
    {'x': 150.0}, {'typeName': 'var_review'}])
def test_unknown_or_invalid_v3_fields_are_rejected(changes):
    with pytest.raises(ValueError):
        adapt_event(raw(**changes))


def test_stoppage_time_orders_by_period_not_clock_seconds():
    first_half_stoppage = adapt_event(raw('pass', 2, period=1, minute=47, second=10))
    second_half = adapt_event(raw('pass', 1, period=2, minute=45, second=5))
    same_second = adapt_event(raw('touch', 3, period=1, minute=47, second=10))
    assert observed([second_half, same_second, first_half_stoppage]) == [same_second, first_half_stoppage, second_half]


def test_history_time_range_with_period_disambiguates_stoppage():
    service = MatchService(MemoryHistory(), MemoryStats())
    data = payload([adapt_event(raw('pass', 1, period=1, minute=46)), adapt_event(raw('pass', 2, period=2, minute=46))])
    service.publish(data)
    both = service.read(data.snapshot.id, 'events', start=2760, end=2820)
    first = service.read(data.snapshot.id, 'events', start=2760, end=2820, period=1)
    assert [e['period'] for e in both['items']] == [1, 2]
    assert [e['event_id'] for e in first['items']] == ['e1']


def write_recording(tmp_path, events, possession=()):
    document = {'synthetic': True, 'match_id': 'match', 'teams': payload().teams, 'players': payload().players,
                'events': events, 'playback': {'duration_seconds': 6.5, 'football_duration_seconds': 5400},
                'capabilities': {'clock': 'broadcast_with_stoppage', **V3_CAPABILITIES},
                'possession_samples': list(possession)}
    path = tmp_path / 'match.json'
    path.write_text(json.dumps(document))
    return RecordingSource(path)


def stoppage_recording(tmp_path):
    boundary = {'x': None, 'y': None, 'teamId': None, 'playerId': None, 'possessionId': None}
    return write_recording(tmp_path, [
        raw('period_start', 1, minute=0, **boundary), raw('pass', 2, minute=47, second=30),
        raw('period_end', 3, minute=48, second=24, **boundary), raw('period_start', 4, period=2, minute=45, **boundary),
        raw('period_end', 5, period=2, minute=94, second=41, **boundary)],
        [{'video_seconds': 1, 'team_id': 'chelsea', 'duration_seconds': 1},
         {'video_seconds': 6, 'team_id': 'manutd', 'duration_seconds': 1}])


def snapshot(source, cursor, clock=None, period=None):
    data = payload(list(source.events[:cursor]))
    data.snapshot.recording_hash = source.fingerprint
    if clock is not None:
        data.snapshot.clock_seconds, data.snapshot.period = clock, period
    data.snapshot.id = data.digest()
    return data.model_copy(update={'events': []})


def test_stoppage_prefix_clock_and_finished_detection(tmp_path):
    source = stoppage_recording(tmp_path)
    # First-half stoppage (47:30 in period 1) precedes the 45:00 second-half restart.
    assert source.materialise(snapshot(source, 3)).snapshot.clock_seconds == 48 * 60 + 24
    assert source.materialise(snapshot(source, 4)).snapshot.clock_seconds == 45 * 60
    with pytest.raises(ValueError, match='Clock'):
        source.materialise(snapshot(source, 4, 5400, 2))
    # Fully released: the real final clock (94:41) and a declared 90:00 final whistle are both finished.
    for clock in (94 * 60 + 41, 5400):
        assert len(source.materialise(snapshot(source, 5, clock, 2)).events) == 5
    with pytest.raises(ValueError, match='Clock'):
        source.materialise(snapshot(source, 5, 5400, 1))
    assert source.possession(5) == {'chelsea': 1, 'manutd': 1}
    assert source.possession(3) == {'chelsea': 1}


def test_v3_fields_are_readable_through_graphql(tmp_path):
    source = write_recording(tmp_path, [raw('shot', 1, outcome='saved', qualifiers=[
        {'type': 'goalMouthY', 'value': 48.2}, {'type': 'bigChance', 'value': True}])])
    service = MatchService(MemoryHistory(), MemoryStats(), source)
    data = snapshot(source, 1)
    service.publish(data, owned=True)
    query = 'query($id:ID!){questionData(snapshotId:$id,operation:"events",eventType:"shot")}'
    result = TestClient(create_app(service)).post('/graphql', json={'query': query, 'variables': {'id': data.snapshot.id}}).json()
    item = result['data']['questionData']['items'][0]
    assert {key: item[key] for key in ('x', 'y', 'possession_id', 'video_seconds', 'sequence', 'outcome')} == {
        'x': 60.5, 'y': 12.25, 'possession_id': 3, 'video_seconds': 1.0, 'sequence': 1, 'outcome': 'saved'}
    assert item['qualifiers'] == {'goalMouthY': 48.2, 'bigChance': True}


V3_CAPABILITIES = {'supported_event_types': ['pass', 'shot', 'goal', 'save', 'clearance', 'aerial', 'take_on',
                                             'ball_recovery', 'offside'], 'shot_outcomes': True}


def test_v3_standard_stats_count_outcomes_once():
    events = rows(('goal', None), ('shot', 'saved'), ('shot', 'blocked'), ('shot', 'off_target'), ('shot', 'post'),
                  ('clearance', 'success'), ('clearance', 'failure'), ('aerial', 'success'), ('aerial', 'failure'),
                  ('take_on', 'success'), ('take_on', 'failure'), ('take_on', 'failure'), ('ball_recovery', None))
    events.append(events[1])
    stats = values(project(payload(events), capabilities=V3_CAPABILITIES))
    expected = {'shots': 5, 'shots_on_target': 2, 'blocked_shots': 1, 'clearances': 2, 'aerials_won': 1,
                'take_ons': 3, 'successful_take_ons': 1, 'ball_recoveries': 1, 'offsides': 0}
    assert {kind: stats[kind]['value'] for kind in expected} == expected


def test_v3_stats_remain_unavailable_without_capabilities():
    stats = values(project(payload(rows(('aerial', 'success'), ('shot', 'blocked'))), capabilities={
        'supported_event_types': ['pass', 'shot', 'goal'], 'shot_outcomes': False}))
    for kind in ('blocked_shots', 'shots_on_target', 'clearances', 'aerials_won', 'take_ons',
                 'successful_take_ons', 'ball_recoveries'):
        assert stats[kind]['available'] is False and stats[kind]['value'] is None


def test_snapshot_identity_ignores_recording_detail_for_v2_producers_and_narrative_reads(tmp_path):
    source = write_recording(tmp_path, [raw('pass', 1)])
    service = MatchService(MemoryHistory(), MemoryStats(), source)
    data = snapshot(source, 1)
    without_detail = payload([source.events[0].model_copy(update={
        'sequence': None, 'video_seconds': None, 'x': None, 'y': None, 'possession_id': None, 'qualifiers': {}})])
    without_detail.snapshot.recording_hash = source.fingerprint
    assert without_detail.digest() == data.snapshot.id
    service.publish(data, owned=True)
    body = TestClient(create_app(service)).get('/demo/snapshots/' + data.snapshot.id).json()
    assert 'x' not in body['events'][0] and body['events'][0]['event_id'] == 'e1'
