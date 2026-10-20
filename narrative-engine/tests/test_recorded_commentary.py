"""Authored fixture contract against the committed recording, not model prompts."""
import hashlib
import json
from pathlib import Path

from narrative_demo.models.snapshots import SnapshotInput
from narrative_demo.services.commentary import CommentaryFixture

ROOT = Path(__file__).resolve().parents[2]


def test_authored_recording_has_every_bucket_each_minute_and_exact_evidence():
    raw = (ROOT / 'data-generation/recordings/chelsea-united-grf.json').read_bytes()
    recording = json.loads(raw)
    fixture = CommentaryFixture(ROOT / 'narrative-engine/fixtures/grf-narratives.json')
    assert fixture.document['recording_hash'] == hashlib.sha256(raw).hexdigest()
    items = fixture.document['items']
    assert len(items) == len({row['text'] for row in items}) == 144
    expected = {f'{team}:{style}' for team in ('home', 'away', 'neutral')
                for style in ('simple', 'casual', 'experienced', 'analytical')}
    originals = {event['eventId']: event for event in recording['events']}
    for minute in range(1, 13):
        group = [row for row in items if row['video_minute'] == minute]
        assert {row['bucket_id'] for row in group} == expected
        for row in group:
            assert row['release_cursor'] <= len(recording['events'])
            assert all(originals[e['event_id']]['typeName'] == e['event_type'] and
                       originals[e['event_id']]['playerId'] == e['player_id'] for e in row['evidence'])
            assert all(originals[e['event_id']]['videoSeconds'] <= minute * 60 for e in row['evidence'])
    assert all(row['clock_seconds'] == 5400 for row in items if row['video_minute'] == 12)
    # Independent recorded-score oracle. Never credit the unidentified second scorer.
    goals = [event for event in recording['events'] if event['typeName'] == 'goal']
    assert [(e['teamId'], e['playerId'], e['timeMin']) for e in goals] == [
        ('manutd', 'manutd-7', 7), ('manutd', None, 8), ('manutd', 'manutd-6', 12), ('manutd', 'manutd-9', 26)]
    assert all('4–0' in row['text'] or 'four' in row['text'].lower() or '0–4' in row['text']
               for row in items if row['video_minute'] == 12)


def test_fixture_release_is_forward_only_and_final_minute_waits_for_tail():
    recording = json.loads((ROOT / 'data-generation/recordings/chelsea-united-grf.json').read_text())
    fixture = CommentaryFixture(ROOT / 'narrative-engine/fixtures/grf-narratives.json')
    # Independent test projection keeps expected fields explicit, outside runtime adapters.
    events = []
    for row in recording['events']:
        qualifiers = {q['type']: q['value'] for q in row.get('qualifiers', [])}
        events.append({'event_id': row['eventId'], 'match_id': row['matchId'], 'revision': row['revision'],
            'event_type': row['typeName'], 'team_id': row['teamId'], 'player_id': row['playerId'],
            'body_part': qualifiers.get('bodyPart'), 'period': row['periodId'],
            'match_time_seconds': row['timeMin'] * 60 + row['timeSec'], 'outcome': row.get('outcome'),
            'distance_metres': qualifiers.get('distanceMetres'), 'deleted': False})
    target = [{'bucket_id': 'neutral:casual'}]
    for minute in range(1, 13):
        row = next(item for item in fixture.document['items'] if item['video_minute'] == minute)
        cursor = row['release_cursor']
        body = {'snapshot': {'id': 'read-only-test', 'run_id': 'test', 'match_id': recording['match_id'],
            'recording_hash': fixture.document['recording_hash'], 'cursor': cursor,
            'clock_seconds': row['clock_seconds'], 'period': row['period'], 'captured_at': 'now'},
            'events': events[:cursor], 'teams': recording['teams'], 'players': recording['players'], 'data_reference': {}}
        payload = SnapshotInput.model_validate(body)
        result = fixture.read(payload, payload.events, target)
        assert len(result) == minute
        if minute == 12:
            payload.snapshot.clock_seconds = 5399
            assert len(fixture.read(payload, payload.events, target)) == 11


def test_native_decision_commentary_matches_exact_recorded_facts():
    recording = json.loads((ROOT / 'data-generation/recordings/chelsea-united-grf.json').read_text())
    fixture = CommentaryFixture(ROOT / 'narrative-engine/fixtures/grf-narratives.json')
    events = recording['events']
    corners = [e for e in events if e['typeName'] == 'corner']
    assert [(e['playerId'], e['timeMin'], e['timeSec']) for e in corners] == [('manutd-8', 11, 41)]
    fouls = [e for e in events if e['typeName'] == 'foul']
    victims = [e for e in events if e['typeName'] == 'foul_won']
    assert [(e['playerId'], e['timeMin'], e['timeSec']) for e in fouls] == [('manutd-0', 75, 19)]
    assert [e['playerId'] for e in victims] == ['chelsea-10']
    eighth_minute = [e for e in events if 420 < e['videoSeconds'] <= 480]
    assert [(e['playerId'], e['timeMin'], e['timeSec']) for e in eighth_minute if e['typeName'] == 'shot'] == [
        ('manutd-9', 57, 40), ('manutd-9', 59, 11)]
    assert [(e['playerId'], e['timeMin'], e['timeSec']) for e in eighth_minute if e['typeName'] == 'offside'] == [
        ('manutd-9', 57, 51), ('manutd-8', 59, 33)]
    late = [item for item in fixture.document['items'] if item['video_minute'] == 11]
    assert all({'foul', 'foul_won', 'offside', 'free_kick'} <= {e['event_type'] for e in item['evidence']}
               for item in late)
