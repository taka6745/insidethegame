"""Recorded media and metadata-only ETL checkpoints share one observed prefix."""
import asyncio
import json

import httpx
import pytest

from backend.adapters.question_data import GraphQLQuestionData
from backend.adapters.replay_source import FixtureEventSource
from backend.adapters.product_demo import load_product_demo
from test_question_data import payload


def recording():
    source = FixtureEventSource()
    spec = dict(source.spec)
    spec['events'] = [dict(event, videoSeconds=index * 0.1) for index, event in enumerate(spec['events'])]
    # Real time: playback runs past the last event; the football duration stays 90 minutes.
    last = spec['events'][-1]['videoSeconds']
    spec['playback'] = {'duration_seconds': last + 30, 'football_duration_seconds': 5400, 'halftime_seconds': last / 2}
    return spec


def test_timed_recording_preserves_event_semantics_and_rejects_reversed_video():
    spec = recording()
    source = FixtureEventSource(content=json.dumps(spec).encode())
    assert source.timed and source.playback_duration == spec['playback']['duration_seconds']
    assert source.playback_seconds(2) == 0.1
    assert source.replay_delay(1, 5) == 0.1
    assert [e.video_seconds for e in source.events] == [e['videoSeconds'] for e in spec['events']]
    assert all(a.same_content(b) for a, b in zip(source.events, FixtureEventSource().events))
    spec['events'][1]['videoSeconds'] = -1
    with pytest.raises(ValueError):
        FixtureEventSource(content=json.dumps(spec).encode())
    spec['events'][1]['videoSeconds'] = 999
    with pytest.raises(ValueError, match='ordered'):
        FixtureEventSource(content=json.dumps(spec).encode())


def test_remote_recording_is_authoritative_no_silent_fixture_fallback(monkeypatch):
    monkeypatch.setenv('DEMO_RECORDING_URL', 'http://etl/demo/recording')
    def fail(*args, **kwargs):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx, 'get', fail)
    with pytest.raises(httpx.ConnectError):
        load_product_demo()


def test_demo_capture_sends_only_checkpoint_not_event_history():
    data = payload(10)
    requests = []
    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={'snapshot_id': data.snapshot.id})
    client = GraphQLQuestionData('http://etl/graphql', bridge='demo', transport=httpx.MockTransport(handler))
    asyncio.run(client.capture(data, purpose='viewer'))
    path, body = requests[0]
    assert path == '/demo/viewer-snapshots'
    assert body['events'] == []
    assert body['snapshot']['cursor'] == len(data.events)
    assert body['snapshot']['id'] == data.snapshot.id
    assert len(data.events) > 0


def test_missing_telemetry_is_unavailable_instead_of_zero():
    from backend.models.rules import Rule
    from backend.services.rule_availability import supported_rule
    capabilities = {'supported_event_types': ['pass', 'shot', 'goal', 'touch'], 'shot_outcomes': False, 'distance_event_types': ['pass']}
    def rule(terms):
        return Rule(match_id='m', predicates=terms)
    assert supported_rule(rule([{'field':'event_type','op':'in','value':['shot','goal']}]), capabilities)
    assert not supported_rule(rule([{'field':'event_type','op':'eq','value':'corner'}]), capabilities)
    assert not supported_rule(rule([{'field':'body_part','op':'eq','value':'head'}]), capabilities)
    assert not supported_rule(rule([{'field':'event_type','op':'eq','value':'shot'}, {'field':'outcome','op':'eq','value':'saved'}]), capabilities)
    assert supported_rule(rule([{'field':'event_type','op':'eq','value':'pass'}, {'field':'outcome','op':'eq','value':'success'}]), capabilities)


def test_question_history_search_distinguishes_unavailable_category_from_empty_page():
    from backend.services.question_tools import QuestionTools
    data = payload(0)
    data.data_reference['capabilities'] = {'supported_event_types': ['pass']}
    class MatchData:
        async def events(self, *args, **kwargs):
            return {'items': [], 'has_more': False, 'total': 0, 'complete': True}
    tools = QuestionTools(data, MatchData(), None, None, [], {}, [])
    assert asyncio.run(tools.events(event_type='corner'))['unavailable']
    assert asyncio.run(tools.events(event_type='pass'))['total'] == 0


def test_distance_sum_requires_recorded_category_coverage():
    from backend.models.rules import Rule
    from backend.services.rule_availability import supported_rule
    cap = {'supported_event_types':['pass','shot','goal','touch'], 'distance_event_types':['pass']}
    def summed(kind):
        return Rule(match_id='m', operation='sum', sum_field='distance_metres', predicates=[{'field':'event_type','op':'eq','value':kind}])
    assert supported_rule(summed('pass'), cap)
    assert not supported_rule(summed('shot'), cap)


def test_grf_reference_describes_contacts_and_partial_player_attribution():
    baseline = FixtureEventSource().data_reference()
    spec = recording()
    spec['provenance'] = {'source': 'Google Research Football instrumented native runtime'}
    source = FixtureEventSource(content=json.dumps(spec).encode())
    reference = source.data_reference()
    assert reference['contract_id'] == 'synthetic-grf-native-contacts-v1'
    assert 'nonintentional deflections' in reference['events']['touch']
    assert 'Count touch records alone' in reference['events']['touch']
    assert 'double-counts' in reference['events']['touch']
    assert 'unknown scorer' in reference['events']['goal']
    assert any('attributed attempts only' in text for text in reference['unavailable'])
    assert reference['schema_sha256'] == baseline['schema_sha256']
    assert FixtureEventSource().data_reference() == baseline


def test_native_v2_reference_keeps_restart_meanings_out_of_old_fixtures():
    baseline = FixtureEventSource().data_reference()
    spec = recording()
    spec['provenance'] = {'source': 'Google Research Football instrumented native runtime'}
    spec['capabilities'] = {'supported_event_types': ['corner', 'pass', 'foul', 'foul_won'],
                            'restart_events': 'taken', 'body_part_event_types': ['pass']}
    reference = FixtureEventSource(content=json.dumps(spec).encode()).data_reference()
    assert reference['contract_id'] == 'synthetic-grf-native-contacts-v2'
    assert 'actually taken' in reference['events']['corner']
    assert 'Referee-whistled' in reference['events']['foul']
    assert 'second_yellow' in reference['events']['card']
    assert not any('Corner-taker identity' in text for text in reference['unavailable'])
    assert 'awarded' in baseline['events']['corner']
    assert FixtureEventSource().data_reference() == baseline


def test_body_part_coverage_is_scoped_to_explicit_categories():
    from backend.models.rules import Rule
    from backend.services.rule_availability import supported_rule
    cap = {'supported_event_types': ['pass', 'shot', 'goal', 'touch', 'corner'],
           'body_parts': False, 'body_part_event_types': ['pass', 'shot', 'goal']}
    head = {'field': 'body_part', 'op': 'eq', 'value': 'head'}
    def headed(*kinds):
        return Rule(match_id='m', predicates=[head, *(
            [{'field': 'event_type', 'op': 'in', 'value': list(kinds)}] if kinds else [])])
    assert supported_rule(headed('pass'), cap)
    assert supported_rule(headed('shot', 'goal'), cap)
    assert not supported_rule(headed('touch'), cap)
    assert not supported_rule(headed('pass', 'corner'), cap)
    assert not supported_rule(headed(), cap)


def test_new_categories_require_recording_coverage_before_history_queries():
    from backend.services.question_tools import QuestionTools
    data = payload(0)
    data.data_reference['capabilities'] = {'supported_event_types': ['offside']}
    class MatchData:
        async def events(self, *args, **kwargs):
            assert kwargs['eventType'] == 'offside'
            return {'items': [], 'has_more': False, 'total': 0, 'complete': True}
    tools = QuestionTools(data, MatchData(), None, None, [], {}, [])
    assert asyncio.run(tools.events(event_type='offside'))['total'] == 0
    assert asyncio.run(tools.events(event_type='penalty'))['unavailable']
    assert asyncio.run(tools.events(event_type='var_review'))['unavailable']
