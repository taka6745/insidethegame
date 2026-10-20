import copy
import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demo_etl.adapters.recording import RecordingSource
from demo_etl.models.snapshot import Event, SnapshotInput, Watermark
from demo_etl.routes.http import create_app
from demo_etl.services.match import MatchService
from demo_etl.services.statistics import observed, project


def event(id='e1', **changes):
    return Event(event_id=id,match_id='match',event_type='pass',team_id='chelsea',player_id='palmer',match_time_seconds=20,**changes)


def payload(events=None, **changes):
    events = events if events is not None else [event()]
    watermark = Watermark(id='',run_id='run',match_id='match',recording_hash='recording',cursor=len(events),
        clock_seconds=max((e.match_time_seconds for e in events),default=None),period=1 if events else None,captured_at='2026-10-19T00:00:00Z',**changes)
    result = SnapshotInput(snapshot=watermark,events=events,teams=[{'id':'chelsea','name':'Chelsea'},{'id':'manutd','name':'Manchester United'}],players=[{'id':'palmer','name':'Cole Palmer','team_id':'chelsea'}],data_reference={})
    result.snapshot.id = result.digest()
    return result


class MemoryHistory:
    def __init__(self): self.rows = {}; self.read_count = 0
    def save(self,payload): self.rows[payload.snapshot.id] = payload
    def read(self,id): self.read_count += 1; return self.rows[id]
    def metadata(self,id): return self.rows[id].model_dump(exclude={'events'})

class MemoryStats:
    def __init__(self): self.rows = {}; self.fail = False
    def save(self,id,match,stats):
        if self.fail: raise RuntimeError('Unavailable')
        self.rows[id] = stats
    def read(self,id): return self.rows[id]


@pytest.fixture
def service(): return MatchService(MemoryHistory(),MemoryStats())


def values(stats, team='chelsea'):
    return {s['id'].split(':')[1]:s for s in stats if s['team_id']==team}


def test_revision_correction_tombstone_and_duplicate():
    original = event()
    correction = original.model_copy(update={'revision':2,'event_type':'goal'})
    deletion = correction.model_copy(update={'revision':3,'deleted':True})
    assert values(project(payload([original,original,correction])))['goals']['value'] == 1
    assert values(project(payload([original,correction,deletion])))['goals']['value'] == 0
    assert observed([correction,original]) == [correction]
    with pytest.raises(ValueError,match='Conflicting'):
        observed([original,correction,original.model_copy(update={'outcome':'failure'})])


def test_measured_possession_and_unavailable_stats():
    stats = values(project(payload(),{'chelsea':30,'manutd':10}))
    assert stats['possession']['value'] == 75
    assert stats['pass_accuracy']['available'] is False
    assert values(project(payload()))['possession']['value'] is None
    assert 'xg' not in stats


def test_pass_accuracy_shots_and_goals():
    events = [event(outcome='success'),event('e2',outcome='failure'),event('e3',outcome='unknown'),
              event('e4').model_copy(update={'event_type':'shot','outcome':'saved'}),event('e5').model_copy(update={'event_type':'goal'})]
    stats = values(project(payload(events)))
    assert stats['passes']['value'] == 3
    assert stats['pass_accuracy']['value'] == 50
    assert stats['shots']['value'] == 2
    assert stats['shots_on_target']['value'] == 2


def test_stats_reads_use_stored_projection_without_history(service):
    data = payload()
    service.publish(data)
    assert service.read(data.snapshot.id,'stats')['stats']
    assert service.history.read_count == 0


def test_incomplete_cross_store_publish_is_not_readable_and_retries(service):
    data = payload(); service.stats.fail = True
    with pytest.raises(RuntimeError): service.publish(data)
    with pytest.raises(KeyError): service.payload(data.snapshot.id)
    service.stats.fail = False
    service.publish(data)
    assert service.payload(data.snapshot.id) == data


def test_history_filters_and_pagination(service):
    data = payload([event(),event('e2').model_copy(update={'match_time_seconds':60,'period':2}),event('e3').model_copy(update={'match_time_seconds':70})])
    service.publish(data)
    first = service.read(data.snapshot.id,'events',limit=1)
    assert first['has_more'] and first['total']==3
    page = service.read(data.snapshot.id,'events',start=60,end=70,eventType='pass',playerId='palmer',period=2)
    assert [e['event_id'] for e in page['items']] == ['e2']
    with pytest.raises(ValueError): service.read(data.snapshot.id,'events',limit=101)


def test_bad_identity_and_wrong_match_rejected(service):
    data = payload(); data.snapshot.id = 'wrong'
    with pytest.raises(ValueError): service.publish(data)
    data = payload(); data.snapshot.match_id = 'other'; data.snapshot.id = data.digest()
    with pytest.raises(ValueError): service.publish(data)


def test_graphql_and_compatibility_contract(service):
    client = TestClient(create_app(service)); data = payload()
    response = client.post('/dev/question-snapshots',json=data.model_dump())
    assert response.status_code == 200
    result = client.post('/graphql',json={'query':'query($id:ID!){questionData(snapshotId:$id,operation:"stats")}','variables':{'id':data.snapshot.id}}).json()
    assert result['data']['questionData']['snapshot_id'] == data.snapshot.id
    assert client.get('/demo/snapshots/'+data.snapshot.id).json()['events'][0]['event_id']=='e1'


def recording(tmp_path):
    data = payload()
    raw = {'synthetic':True,'match_id':'match','teams':data.teams,'players':data.players,
        'events':[{'eventId':'e1','matchId':'match','typeName':'pass','teamId':'chelsea','playerId':'palmer','periodId':1,'timeMin':0,'timeSec':20,'videoSeconds':2}],
        'possession_samples':[{'video_seconds':1,'team_id':'chelsea','duration_seconds':1},{'video_seconds':3,'team_id':'manutd','duration_seconds':1}]}
    path=tmp_path/'match.json';path.write_text(json.dumps(raw));return RecordingSource(path)


def test_owned_recording_materializes_metadata_only_prefix(service,tmp_path):
    service.recording=recording(tmp_path)
    data=payload();data.snapshot.recording_hash=service.recording.fingerprint;data.snapshot.id=data.digest()
    body=data.model_dump();body.pop('events')
    client=TestClient(create_app(service))
    assert client.post('/demo/viewer-snapshots',json=body).status_code==200
    assert service.payload(data.snapshot.id).events == data.events
    assert values(service.read(data.snapshot.id,'stats')['stats'])['possession']['value']==100
    assert client.get('/demo/recording').content==service.recording.content
    body['snapshot']['recording_hash']='foreign'
    assert client.post('/demo/snapshots',json=body).status_code==422


def test_postgres_persistence_and_immutable_prefix():
    history_url=os.environ.get('ETL_TEST_HISTORY_DATABASE_URL')
    stats_url=os.environ.get('ETL_TEST_STATS_DATABASE_URL')
    if not history_url or not stats_url: pytest.skip('Set ETL_TEST_HISTORY_DATABASE_URL and ETL_TEST_STATS_DATABASE_URL for real DB tests')
    from demo_etl.repositories.history import HistoryRepository
    from demo_etl.repositories.stats import StatsRepository
    history=HistoryRepository(history_url);stats=StatsRepository(stats_url)
    history.initialize();stats.initialize();service=MatchService(history,stats)
    data=payload();data.snapshot.run_id=str(uuid.uuid4());data.snapshot.id=data.digest()
    service.publish(data);service.publish(data)
    restarted=MatchService(HistoryRepository(history_url),StatsRepository(stats_url))
    assert restarted.payload(data.snapshot.id)==data
    altered=data.model_copy(deep=True);altered.events[0]=event(outcome='failure');altered.snapshot.id=altered.digest()
    with pytest.raises(ValueError,match='immutable'): restarted.publish(altered)
    from psycopg import connect
    with connect(history_url) as conn:
        assert conn.execute('SELECT count(*) FROM demo_deliveries WHERE run_id=%s',(data.snapshot.run_id,)).fetchone()[0]==1


def test_grf_capabilities_do_not_invent_metrics_or_double_count_scoring_shots():
    events=[event().model_copy(update={'event_type':'shot'}),event('goal').model_copy(update={'event_type':'goal'})]
    stats=values(project(payload(events),capabilities={'supported_event_types':['pass','shot','goal','touch'],
        'shots_include_scoring_attempts':True,'shot_outcomes':False}))
    assert stats['shots']['value']==1
    assert stats['goals']['value']==1
    assert stats['shots']['event_types']==['shot']
    for kind in ('cards','corners','saves','shots_on_target'):
        assert stats[kind]['available'] is False
        assert stats[kind]['value'] is None


def test_final_clock_exposes_tail_ownership_but_not_future_events(service,tmp_path):
    source=recording(tmp_path)
    source.document['playback']={'football_duration_seconds':5400,'duration_seconds':720}
    service.recording=source
    data=payload();data.snapshot.recording_hash=source.fingerprint
    data.snapshot.clock_seconds=5400;data.snapshot.period=2;data.snapshot.id=data.digest()
    service.publish(data.model_copy(update={'events':[]}),owned=True)
    assert values(service.read(data.snapshot.id,'stats')['stats'])['possession']['value']==50
    assert service.read(data.snapshot.id,'events')['total']==1


def test_snapshot_prefix_does_not_advance_when_later_snapshot_is_published(service):
    first=payload();service.publish(first)
    later=payload([event(),event('e2').model_copy(update={'event_type':'goal','match_time_seconds':70})]);service.publish(later)
    assert values(service.read(first.snapshot.id,'stats')['stats'])['goals']['value']==0
    assert values(service.read(later.snapshot.id,'stats')['stats'])['goals']['value']==1
    assert service.read(first.snapshot.id,'events')['total']==1


def test_new_run_keeps_old_snapshot_readable_without_mixing_events(service):
    first=payload();service.publish(first)
    new=payload([]);new.snapshot.run_id='new-run';new.snapshot.id=new.digest();service.publish(new)
    assert service.read(new.snapshot.id,'events')['items']==[]
    assert service.read(first.snapshot.id,'events')['total']==1
