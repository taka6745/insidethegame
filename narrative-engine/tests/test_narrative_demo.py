import asyncio
import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from narrative_demo.app import create_app
from narrative_demo.models.snapshots import SnapshotInput
from narrative_demo.repositories.snapshots import SnapshotRepository
from narrative_demo.services.commentary import CommentaryFixture
from narrative_demo.services.narratives import NarrativeService
from narrative_demo.services.recaps import build_recaps
from narrative_demo.adapters.events import observed_events


def event(identifier, seconds, kind='pass', **extra):
    return {'event_id': identifier, 'match_id': 'match', 'revision': 1, 'event_type': kind,
            'team_id': 'CHE', 'player_id': 'palmer', 'match_time_seconds': seconds,
            'period': 1 if seconds < 2700 else 2, 'deleted': False, **extra}


def payload(events=None, clock=120, recording_hash='recording'):
    events = events if events is not None else [event('pass', 30), event('goal', 100, 'goal')]
    body = {'snapshot': {'id': 'pending', 'run_id': 'run', 'match_id': 'match',
                        'recording_hash': recording_hash, 'cursor': len(events),
                        'clock_seconds': clock, 'period': 1, 'captured_at': 'now'},
            'events': events, 'teams': [{'id': 'CHE', 'name': 'Chelsea'}, {'id': 'MUN', 'name': 'Manchester United'}],
            'players': [{'id': 'palmer', 'name': 'Cole Palmer'}], 'data_reference': {}}
    raw = copy.deepcopy(body)
    raw['snapshot'].pop('id')
    raw['snapshot'].pop('captured_at')
    body['snapshot']['id'] = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return SnapshotInput.model_validate(body)


def fixture(tmp_path, source):
    path = tmp_path / 'narratives.json'
    items = []
    for bucket in ('home:simple', 'away:analytical'):
        items.append({'id': bucket + ':minute-1', 'bucket_id': bucket, 'release_cursor': 2,
                      'clock_seconds': 120, 'period': 1, 'evidence': [source.events[1]],
                      'text': 'Cole Palmer has scored for Chelsea.', 'stat_ids': ['CHE:goals']})
    path.write_text(json.dumps({'recording_hash': 'recording', 'items': items}))
    return CommentaryFixture(path)


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


def setup(tmp_path):
    source = payload()
    audience = Audience()
    service = NarrativeService(SnapshotRepository(str(tmp_path / 'memory.sqlite3')), Etl(source),
                               audience, fixture(tmp_path, source))
    metadata = source.model_copy(update={'events': []})
    return service, source, metadata, audience


def test_fixture_only_returns_enabled_observed_bucket(tmp_path):
    source = payload()
    author = fixture(tmp_path, source)
    rows = author.read(source, observed_events(source.events), [{'bucket_id': 'home:simple'}])
    assert len(rows) == 1
    assert rows[0]['buckets'] == ['home:simple']
    assert rows[0]['evidence_ids'] == ['goal']
    assert author.read(source, observed_events(source.events), []) == []


def test_fixture_rejects_future_recording_and_deleted_or_corrected_evidence(tmp_path):
    source = payload()
    author = fixture(tmp_path, source)
    target = [{'bucket_id': 'home:simple'}]
    assert author.read(payload([event('pass', 30)], clock=60), [event('pass', 30)], target) == []
    assert author.read(payload(recording_hash='other'), source.events, target) == []
    for change in ({'revision': 2, 'deleted': True}, {'revision': 2, 'event_type': 'shot'}):
        revised = payload(source.events + [dict(source.events[1], **change)])
        assert author.read(revised, observed_events(revised.events), target) == []


def test_question_read_does_not_fetch_audience_or_author(tmp_path):
    service, source, metadata, audience = setup(tmp_path)
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
    assert second['text'] == 'Cole Palmer has scored for Chelsea.'
    asyncio.run(service.capture(metadata, viewer=False))
    assert service.read(source.snapshot.id, 'viewer')['items'] == [second]


def test_recaps_cover_without_overlap_retain_children_and_exclude_future():
    source = payload([event('first', 30), event('second', 2800, 'goal')], clock=2940)
    result = build_recaps(source, source.events)
    blocks = result['blocks']
    assert blocks[0]['tier'] == 'half'
    assert blocks[0]['start_seconds'] == 0 and blocks[-1]['end_seconds'] == 2940
    assert all(left['end_seconds'] == right['start_seconds'] for left, right in zip(blocks, blocks[1:]))
    assert all(row['end_seconds'] <= 2940 for row in result['archive'])
    archive = {row['id']: row for row in result['archive']}
    assert all(child in archive for row in blocks for child in row['child_ids'])
    assert 'goal' not in blocks[0]['summary']
    assert all(archive[child]['superseded_by'] == row['id'] for row in result['archive'] for child in row['child_ids'])


@pytest.mark.parametrize('clock', [0, 59, 60, 299, 300, 599, 600, 1199, 1200, 2699, 2700, 5399, 5400])
def test_compact_coverage_at_boundaries(clock):
    source = payload([], clock=clock)
    blocks = build_recaps(source, [])['blocks']
    assert sum(row['end_seconds'] - row['start_seconds'] for row in blocks) == clock // 60 * 60
    if blocks:
        assert blocks[0]['start_seconds'] == 0
        assert all(a['end_seconds'] == b['start_seconds'] for a, b in zip(blocks, blocks[1:]))


def test_snapshot_hash_and_watermark_are_verified():
    good = payload()
    good.verify()
    good.events[1]['match_time_seconds'] = 500
    with pytest.raises(ValueError, match='observed match clock'):
        good.verify()
    good.events[1]['match_time_seconds'] = 110
    with pytest.raises(ValueError, match='ID'):
        good.verify()


def test_persistence_and_snapshot_isolation(tmp_path):
    service, first, metadata, _ = setup(tmp_path)
    asyncio.run(service.capture(metadata, viewer=True))
    newer = payload(first.events + [event('later', 150, 'goal')], clock=180)
    service.etl.source = newer
    asyncio.run(service.capture(newer.model_copy(update={'events': []}), viewer=False))
    service.repository.close()
    repository = SnapshotRepository(str(tmp_path / 'memory.sqlite3'))
    assert 'later' not in json.dumps(repository.read(first.snapshot.id))
    assert 'later' in json.dumps(repository.read(newer.snapshot.id))
    repository.close()


def test_http_metadata_only_graphql_archive_and_unsupported_reads(tmp_path):
    service, source, metadata, _ = setup(tmp_path)
    with TestClient(create_app(service)) as client:
        assert client.post('/demo/viewer-snapshots', json=source.model_dump()).status_code == 422
        assert client.post('/demo/viewer-snapshots', json=metadata.model_dump()).status_code == 200
        body = {'query': 'query($id: ID!){questionData(snapshotId:$id,operation:"recaps",tier:"minute")}',
                'variables': {'id': source.snapshot.id}}
        rows = client.post('/graphql', json=body).json()['data']['questionData']['items']
        assert len(rows) == 2
        body['query'] = 'query($id: ID!){questionData(snapshotId:$id,operation:"stats")}'
        assert client.post('/graphql', json=body).json()['errors']


def test_final_commentary_waits_for_full_time_even_at_final_cursor(tmp_path):
    source = payload(clock=5400)
    author = fixture(tmp_path, source)
    author.document['items'][0]['clock_seconds'] = 5400
    target = [{'bucket_id': 'home:simple'}]
    assert author.read(payload(clock=5390), source.events, target) == []
    assert len(author.read(source, source.events, target)) == 1


def test_prefix_guard_invalidates_unquoted_earlier_event_correction(tmp_path):
    source = payload()
    author = fixture(tmp_path, source)
    author.document['items'][0]['prefix_digest'] = hashlib.sha256(
        json.dumps(source.events, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    target = [{'bucket_id': 'home:simple'}]
    assert author.read(source, source.events, target)
    revised = payload(source.events + [dict(source.events[0], revision=2, event_type='goal')])
    assert author.read(revised, observed_events(revised.events), target) == []


def test_catalogue_failure_never_silently_enables_buckets(tmp_path):
    import httpx
    service, source, metadata, _ = setup(tmp_path)
    class Unavailable:
        async def read(self, match_id):
            raise httpx.ConnectError('offline')
    service.audience = Unavailable()
    with TestClient(create_app(service)) as client:
        assert client.post('/demo/viewer-snapshots', json=metadata.model_dump()).status_code == 503
        assert client.post('/demo/question-snapshots', json=metadata.model_dump()).status_code == 200
        assert service.read(source.snapshot.id, 'viewer')['items'] == []
