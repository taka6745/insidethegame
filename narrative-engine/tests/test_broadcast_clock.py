"""Stoppage-time ordering, period-based recaps, N-minute binding and cursor-bounded reads."""
import asyncio
import random

import pytest
from fastapi.testclient import TestClient

from narrative_demo.adapters.events import observed_events
from narrative_demo.app import create_app
from narrative_demo.models.fixtures import BUCKETS
from narrative_demo.services.commentary import CommentaryFixture
from narrative_demo.services.recaps import build_recaps
from synthetic import EVENTS, HASH, at, event, export, fixture_file, payload, text
from test_narrative_demo import setup
from tools.bind_commentary import bind


def test_first_half_stoppage_orders_before_second_half_kick_off():
    shuffled = EVENTS[:]
    random.Random(4).shuffle(shuffled)
    assert [row['event_id'] for row in observed_events(shuffled)] == [row['event_id'] for row in EVENTS]
    # Same clock second keeps delivery (sequence) order.
    tied = [event('a', 60), event('b', 60), event('a', 60, revision=2)]
    assert [row['event_id'] for row in observed_events(tied)] == ['a', 'b']


def test_verify_accepts_stoppage_before_later_period_and_rejects_future():
    at(9).verify()  # 46:30 in period 1 precedes 45:30 in period 2
    future = payload(EVENTS[:9], clock=2700, period=1)
    with pytest.raises(ValueError, match='observed match clock'):
        future.verify()


def test_halves_split_by_period_not_clock():
    source = at(11)
    result = build_recaps(source, observed_events(source.events))
    halves = [row for row in result['blocks']]
    assert [(row['tier'], row['period'], row['start_seconds'], row['end_seconds']) for row in halves] == [
        ('half', 1, 0, 2820), ('half', 2, 2700, 2820)]
    assert 'Chelsea: 1 goal' in halves[0]['summary'] and 'Manchester United: 1 goal' in halves[1]['summary']
    assert 'Manchester United: 1 goal' not in halves[0]['summary']
    stoppage = [row for row in result['archive'] if row['tier'] == 'minute' and row['period'] == 1
                and row['start_seconds'] >= 2700]
    assert len(stoppage) == 2 and all(row['superseded_by'] == halves[0]['id'] for row in stoppage)
    assert result['tail'] == []


def test_open_stoppage_minute_stays_in_tail():
    source = at(6)  # 45+2 shot observed, minute not complete
    result = build_recaps(source, observed_events(source.events))
    assert result['blocks'][-1]['end_seconds'] == 2760 and not any(row['tier'] == 'half' for row in result['archive'])
    assert [row['event_id'] for row in result['tail']] == ['shot-1']


def test_binds_every_broadcast_minute_including_stoppage():
    document = bind(text(), export(), HASH)
    minutes = {row['id']: row for row in document['minutes']}
    assert len(minutes) == 47 + 2
    assert (minutes['p1-m47']['label'], minutes['p2-m46']['label']) == ("45+2'", "46'")
    assert all(len(row['narratives']) == len(BUCKETS) for row in minutes.values())
    assert [minutes[m]['release']['cursor'] for m in ('p1-m1', 'p1-m45', 'p1-m46', 'p1-m47', 'p2-m46', 'p2-m47')] == [
        3, 5, 6, 7, 10, 11]
    assert minutes['p1-m46']['release']['video_seconds'] == 2770
    assert [row['release']['cursor'] for row in document['tiers']] == [4, 7, 11]
    assert {row['id']: row['release']['cursor'] for row in document['key_moments']} == {'km-opener': 4, 'km-late': 11}


@pytest.mark.parametrize('broken', ['minute', 'bucket', 'hash', 'tier', 'moment'])
def test_binder_rejects_incomplete_or_inconsistent_authoring(broken):
    authored, reviewed = text(), HASH
    if broken == 'minute':
        authored['minutes'].pop('p1-m46')
    elif broken == 'bucket':
        authored['minutes']['p2-m47']['narratives'].pop('neutral:casual')
    elif broken == 'hash':
        reviewed = 'b' * 64
    elif broken == 'tier':
        authored['tiers'][2]['child_ids'] = ['p1-m47', 'p2-m46']
    else:
        authored['key_moments'][0]['event_ids'] = ['unknown']
    with pytest.raises(ValueError):
        bind(authored, export(), reviewed)


def graphql(client, field, snapshot_id, arguments=''):
    query = f'query($id: ID!){{{field}(snapshotId:$id{arguments})}}'
    body = client.post('/graphql', json={'query': query, 'variables': {'id': snapshot_id}}).json()
    assert 'errors' not in body, body
    return body['data'][field]


def capture(tmp_path, cursor):
    service, source, metadata, _ = setup(tmp_path, at(cursor))
    asyncio.run(service.capture(metadata, viewer=False))
    return service, source.snapshot.id


def test_graphql_reads_are_bounded_by_the_snapshot_cursor(tmp_path):
    service, early = capture(tmp_path, 9)
    later = at(11)
    service.etl.source = later
    asyncio.run(service.capture(later.model_copy(update={'events': []}), viewer=False))
    with TestClient(create_app(service)) as client:
        minutes = graphql(client, 'minuteRecaps', early)
        assert len(minutes['items']) == 47 and {row['period'] for row in minutes['items']} == {1}
        assert minutes['items'][-1]['label'] == "45+2'"
        assert len(graphql(client, 'minuteRecaps', later.snapshot.id, ', period:2')['items']) == 2
        # Only the released moment, re-ranked so future bigger moments are not implied.
        assert [(row['id'], row['rank']) for row in graphql(client, 'keyMoments', early)['items']] == [('km-opener', 1)]
        assert [(row['id'], row['rank']) for row in graphql(client, 'keyMoments', later.snapshot.id)['items']] == [
            ('km-late', 1), ('km-opener', 2)]
        assert [row['id'] for row in graphql(client, 'tierRecaps', early)['items']] == ['p1-half', 'p1-five-1']
        assert graphql(client, 'tierRecaps', later.snapshot.id, ', tier:"half", period:2')['items'][0]['id'] == 'p2-half'
        context = graphql(client, 'narrativeContext', early)
        assert [row['id'] for row in context['blocks']] == ['p1-half']
        assert [row['event_id'] for row in context['tail']] == ['p2-start', 'shot-2']
        assert [row['event_id'] for row in context['key_events']] == ['goal-1', 'card-1']
        same = graphql(client, 'questionData', early, ', operation:"key_moments"')
        assert same['items'] == graphql(client, 'keyMoments', early)['items']


def test_tier_waits_for_children_and_falls_back_when_a_child_changes(tmp_path):
    author = CommentaryFixture(fixture_file(tmp_path))
    source = at(5)
    neutral = author.neutral(source, observed_events(source.events))
    assert [row['id'] for row in neutral['tiers']] == ['p1-five-1']
    assert neutral['context']['blocks'][0]['id'] == 'p1-five-1'
    assert 'p1-m3' not in [row['id'] for row in neutral['context']['blocks']]
    other = author.neutral(at(5, recording_hash='b' * 64), EVENTS[:5])
    assert other['minutes'] == other['tiers'] == other['key_moments'] == [] and other['context']['blocks'] == []
