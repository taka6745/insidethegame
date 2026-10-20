import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from narrative_demo.adapters.events import observed_events
from narrative_demo.app import create_app
from narrative_demo.repositories.snapshots import SnapshotRepository
from narrative_demo.services.commentary import CommentaryFixture
from narrative_demo.services.narratives import NarrativeService
from narrative_demo.services.recaps import build_recaps
from synthetic import EVENTS, at, event, fixture_file, payload


class Etl:
    def __init__(self, source):
        self.source = source

    async def read(self, snapshot_id):
        return self.source


class Audience:
    def __init__(self):
        self.calls = 0
        self.targets = [{'bucket_id': 'home:simple'}]

    async def read(self, match_id):
        self.calls += 1
        return {'match_id': match_id, 'revision': self.calls, 'generation_targets': self.targets}


def setup(tmp_path, source=None):
    source = source or at(3)
    audience = Audience()
    service = NarrativeService(SnapshotRepository(str(tmp_path / 'memory.sqlite3')), Etl(source),
                               audience, CommentaryFixture(fixture_file(tmp_path)))
    metadata = source.model_copy(update={'events': []})
    return service, source, metadata, audience


def test_fixture_only_returns_enabled_observed_bucket(tmp_path):
    source = at(3)
    author = CommentaryFixture(fixture_file(tmp_path))
    rows = author.read(source, observed_events(source.events), [{'bucket_id': 'home:simple'}])
    assert [row['id'] for row in rows] == ['p1-m1:home:simple']
    assert rows[0]['buckets'] == ['home:simple'] and rows[0]['evidence_ids'] == ['p1-start', 'goal-1']
    assert set(rows[0]) == {'id', 'text', 'clock_seconds', 'period', 'buckets', 'stat_ids', 'synthetic', 'evidence_ids'}
    assert author.read(source, observed_events(source.events), []) == []


def test_fixture_rejects_future_recording_and_deleted_or_corrected_evidence(tmp_path):
    source = at(3)
    author = CommentaryFixture(fixture_file(tmp_path))
    target = [{'bucket_id': 'home:simple'}]
    assert author.read(at(2), observed_events(at(2).events), target) == []
    assert author.read(at(3, recording_hash='b' * 64), source.events, target) == []
    for change in ({'revision': 2, 'deleted': True}, {'revision': 2, 'event_type': 'shot'}):
        revised = payload(source.events + [dict(source.events[2], **change)], clock=100)
        assert author.read(revised, observed_events(revised.events), target) == []


def test_question_read_does_not_fetch_audience_or_author(tmp_path):
    service, source, metadata, audience = setup(tmp_path, at(4))
    asyncio.run(service.capture(metadata, viewer=False))
    assert audience.calls == 0
    assert service.read(source.snapshot.id, 'viewer')['items'] == []
    assert 'Chelsea: 1 goal events' in str(service.read(source.snapshot.id, 'compact'))


def test_viewer_switch_updates_available_bucket_without_changing_text(tmp_path):
    service, source, metadata, audience = setup(tmp_path)
    asyncio.run(service.capture(metadata, viewer=True))
    first = service.read(source.snapshot.id, 'viewer')['items'][0]
    audience.targets = [{'bucket_id': 'away:analytical'}]
    asyncio.run(service.capture(metadata, viewer=True))
    second = service.read(source.snapshot.id, 'viewer')['items'][0]
    assert first['buckets'] == ['home:simple'] and second['buckets'] == ['away:analytical']
    assert second['text'] == 'away:analytical on p1-m1.'
    asyncio.run(service.capture(metadata, viewer=False))
    assert service.read(source.snapshot.id, 'viewer')['items'] == [second]


def test_recaps_cover_without_overlap_retain_children_and_exclude_future():
    source = payload([event('first', 30), event('second', 2800, 'goal', 1)], clock=2940, period=1)
    result = build_recaps(source, source.events)
    blocks = result['blocks']
    assert blocks[0]['start_seconds'] == 0 and blocks[-1]['end_seconds'] == 2940
    assert all(left['end_seconds'] == right['start_seconds'] for left, right in zip(blocks, blocks[1:]))
    assert all(row['end_seconds'] <= 2940 for row in result['archive'])
    archive = {row['id']: row for row in result['archive']}
    assert all(child in archive for row in blocks for child in row['child_ids'])
    assert 'goal' not in blocks[0]['summary']
    assert 'goal' in next(row['summary'] for row in blocks if row['start_seconds'] <= 2800 < row['end_seconds'])
    assert all(archive[child]['superseded_by'] == row['id'] for row in result['archive'] for child in row['child_ids'])


@pytest.mark.parametrize('period,clock', [(1, 0), (1, 59), (1, 60), (1, 299), (1, 300), (1, 599), (1, 600),
                                          (1, 1199), (1, 1200), (1, 2699), (1, 2700), (1, 2950),
                                          (2, 2700), (2, 2759), (2, 5399), (2, 5400), (2, 5700)])
def test_compact_coverage_at_boundaries(period, clock):
    source = payload([], clock=clock, period=period)
    blocks = build_recaps(source, [])['blocks']
    start = 0 if period == 1 else 2700
    assert sum(row['end_seconds'] - row['start_seconds'] for row in blocks) == clock // 60 * 60 - start
    if blocks:
        assert blocks[0]['start_seconds'] == start
        assert all(a['end_seconds'] == b['start_seconds'] for a, b in zip(blocks, blocks[1:]))


def test_snapshot_hash_and_watermark_are_verified():
    good = at(3)
    good.verify()
    good.events[2]['match_time_seconds'] = 500
    with pytest.raises(ValueError, match='observed match clock'):
        good.verify()
    good.events[2]['match_time_seconds'] = 90
    with pytest.raises(ValueError, match='ID'):
        good.verify()


def test_persistence_and_snapshot_isolation(tmp_path):
    service, first, metadata, _ = setup(tmp_path)
    asyncio.run(service.capture(metadata, viewer=True))
    newer = at(5)
    service.etl.source = newer
    asyncio.run(service.capture(newer.model_copy(update={'events': []}), viewer=False))
    service.repository.close()
    repository = SnapshotRepository(str(tmp_path / 'memory.sqlite3'))
    assert 'card-1' not in json.dumps(repository.read(first.snapshot.id))
    assert 'card-1' in json.dumps(repository.read(newer.snapshot.id))
    repository.close()


def test_http_metadata_only_graphql_archive_and_unsupported_reads(tmp_path):
    service, source, metadata, _ = setup(tmp_path)
    with TestClient(create_app(service)) as client:
        assert client.get('/health').json()['authored_minutes'] == 49
        assert client.post('/demo/viewer-snapshots', json=source.model_dump()).status_code == 422
        assert client.post('/demo/viewer-snapshots', json=metadata.model_dump()).status_code == 200
        body = {'query': 'query($id: ID!){questionData(snapshotId:$id,operation:"recaps",tier:"minute")}',
                'variables': {'id': source.snapshot.id}}
        rows = client.post('/graphql', json=body).json()['data']['questionData']['items']
        assert len(rows) == 1
        body['query'] = 'query($id: ID!){questionData(snapshotId:$id,operation:"stats")}'
        assert client.post('/graphql', json=body).json()['errors']


def test_final_commentary_waits_for_full_time_even_at_final_cursor(tmp_path):
    author = CommentaryFixture(fixture_file(tmp_path))
    target = [{'bucket_id': 'home:simple'}]
    assert [row['id'] for row in author.read(at(11), EVENTS, target)][-1] == 'p2-m47:home:simple'
    assert 'p2-m47:home:simple' not in [row['id'] for row in author.read(at(10), EVENTS[:10], target)]
    early = at(11, clock=2770)
    assert 'p2-m47:home:simple' not in [row['id'] for row in author.read(early, EVENTS, target)]


def test_prefix_guard_invalidates_unquoted_earlier_event_correction(tmp_path):
    source = at(4)
    author = CommentaryFixture(fixture_file(tmp_path))
    target = [{'bucket_id': 'home:simple'}]
    assert author.read(source, observed_events(source.events), target)
    revised = payload(source.events + [dict(source.events[1], revision=2, event_type='shot')], clock=2690)
    assert author.read(revised, observed_events(revised.events), target) == []
    inserted = payload(source.events + [event('late-insert', 50)], clock=2690)
    assert [row['id'] for row in author.read(inserted, observed_events(inserted.events), target)] == []


def test_catalogue_failure_never_silently_enables_buckets(tmp_path):
    service, source, metadata, _ = setup(tmp_path)

    class Unavailable:
        async def read(self, match_id):
            raise httpx.ConnectError('offline')
    service.audience = Unavailable()
    with TestClient(create_app(service)) as client:
        assert client.post('/demo/viewer-snapshots', json=metadata.model_dump()).status_code == 503
        assert client.post('/demo/question-snapshots', json=metadata.model_dump()).status_code == 200
        assert service.read(source.snapshot.id, 'viewer')['items'] == []
