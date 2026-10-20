"""Scripted commentary follows received evidence, not the wall clock or future file."""
from types import SimpleNamespace

import pytest

from backend.adapters.replay_source import FixtureEventSource
from backend.fake_product_narratives import FIXTURES, viewer_narratives, _moments
from backend.fake_question_data import observed_events


def snapshot(filename='product-demo.json', count=35):
    source = FixtureEventSource(FIXTURES / filename)
    payload = SimpleNamespace(
        snapshot=SimpleNamespace(recording_hash=source.fingerprint, match_id=source.match_id),
        events=list(source.history(count)), teams=source.spec['teams'], players=source.spec['players'])
    return payload


def messages(payload):
    return viewer_narratives(payload, observed_events(payload.events))['items']


@pytest.mark.parametrize('filename', ['product-demo.json', 'filter-lab.json'])
def test_six_story_beats_have_twelve_distinct_bucket_versions(filename):
    payload = snapshot(filename)
    items = messages(payload)
    assert len(items) == 6 * 12
    assert len({item['id'] for item in items}) == len(items)
    for moment in _moments():
        beat = [i for i in items if f":{moment['id']}:" in i['id']]
        assert len(beat) == len({i['text'] for i in beat}) == 12
        assert {i['buckets'][0] for i in beat} == {
            f'{team}:{style}' for team in ('chelsea', payload.teams[1]['id'], 'neutral')
            for style in ('simple', 'casual', 'experienced', 'analytical')}
        assert all(len(i['text']) <= 330 and '{' not in i['text'] and i['synthetic'] for i in beat)
        assert all(len(i['stat_ids']) == 5 for i in beat)
    # The original lab recording uses its own roster, not Chelsea–United names.
    if filename == 'filter-lab.json':
        assert not any('Bruno' in i['text'] or 'Manchester' in i['text'] for i in items)


def test_every_delivery_prefix_only_publishes_supported_moments():
    for count in range(36):
        payload = snapshot(count=count)
        observed = {e.event_id for e in observed_events(payload.events)}
        expected = [m for m in _moments() if m['trigger_event_id'] in observed
                    and set(m['required_event_ids']) <= observed
                    and not set(m.get('absent_event_ids', ())) & observed]
        actual = messages(payload)
        assert len(actual) == len(expected) * 12
        assert all(i['clock_seconds'] <= max((e.match_time_seconds for e in payload.events), default=0)
                   for i in actual)
    assert messages(snapshot(count=9)) == []
    assert len(messages(snapshot(count=10))) == 12


def test_corrections_and_duplicate_delivery_do_not_create_commentary_spam():
    # Goal e7 is retracted before the first beat. A duplicated e17 at the end
    # must not publish another copy of the corner-pattern narrative.
    assert messages(snapshot(count=7)) == messages(snapshot(count=8)) == []
    assert messages(snapshot(count=34)) == messages(snapshot(count=35))
    assert not any('40:00' in i['text'] for i in messages(snapshot()))


def test_unrecognised_or_edited_recording_does_not_inherit_scripted_facts():
    payload = snapshot()
    payload.snapshot.recording_hash = 'unknown'
    assert messages(payload) == []
    payload = snapshot()
    payload.events[-2] = payload.events[-2].model_copy(update={'event_type': 'goal'})
    assert messages(payload) == []
    payload = snapshot()
    payload.players = [{**p, 'name': 'Edited roster'} for p in payload.players]
    assert messages(payload) == []


def test_removing_supporting_event_withdraws_affected_story():
    payload = snapshot()
    events = [e for e in observed_events(payload.events) if e.event_id != 'e22']
    items = viewer_narratives(payload, events)['items']
    assert all(i['clock_seconds'] < 80 * 60 for i in items)
