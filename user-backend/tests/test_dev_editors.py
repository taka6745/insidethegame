"""Developer-edited configuration: answer prices (served to viewers) and demo profiles."""
import pytest
from psycopg.types.json import Jsonb

from harness import Running
from support import path, start

ORIGINAL_PROFILES = [
    {'id': 'neutral-simple', 'display_name': 'New viewer', 'selections': {'team': 'neutral', 'fan_style': 'simple'}},
    {'id': 'riverton-analytical', 'display_name': 'Home analyst', 'selections': {'team': 'home', 'fan_style': 'analytical'}},
    {'id': 'united-casual', 'display_name': 'Away fan', 'selections': {'team': 'away', 'fan_style': 'casual'}}]


def test_viewer_prices_come_from_the_config_table_with_etag(store):
    with Running(store) as run:
        response = run.client.get('/product/prices')
        assert response.json() == {'input': 0.4, 'output': 1.6, 'revision': 1}
        tag = response.headers['etag']
        assert run.client.get('/product/prices', headers={'If-None-Match': tag}).status_code == 304
        saved = run.client.put('/dev/config/prices', json={'expected_revision': 1, 'value': {'input': 2.5, 'output': 10}})
        assert saved.json() == {'table': 'prices', 'revision': 2, 'value': {'input': 2.5, 'output': 10.0}}
        changed = run.client.get('/product/prices', headers={'If-None-Match': tag})
        assert changed.status_code == 200 and changed.json() == {'input': 2.5, 'output': 10.0, 'revision': 2}
        for value in ({'input': -1, 'output': 1}, {'input': 1}, {'input': 1, 'output': 1, 'model': 'x'}):
            assert run.client.put('/dev/config/prices', json={'expected_revision': 2, 'value': value}).status_code == 422
        assert run.client.put('/dev/config/prices', json={'expected_revision': 1, 'value': {'input': 1, 'output': 1}}).status_code == 409
        assert run.client.get('/dev/config/stream').json()['value'] == {'gap_timeout_seconds': 30.0}



def test_the_storyline_policy_is_served_to_the_engine_and_edited_under_dev(store):
    import json
    from backend.store import MIGRATIONS
    seed = json.loads((MIGRATIONS / 'seeds' / 'storyline-policy.json').read_text())
    with Running(store) as run:
        response = run.client.get('/storyline-policy')
        assert response.json() == {'table': 'storyline-policy', 'revision': 1, 'value': seed}
        tag = response.headers['etag']
        assert run.client.get('/storyline-policy', headers={'If-None-Match': tag}).status_code == 304
        edited = {**seed, 'storylines': {**seed['storylines'], 'max_active': 3}}
        assert run.client.put('/dev/config/storyline-policy',
                              json={'expected_revision': 1, 'value': edited}).status_code == 200
        changed = run.client.get('/storyline-policy', headers={'If-None-Match': tag})
        assert changed.status_code == 200 and changed.json()['value']['storylines']['max_active'] == 3
        bad = {**seed, 'analysis': {**seed['analysis'], 'confidence_cap_short': 0.95}}  # above the long cap
        assert run.client.put('/dev/config/storyline-policy',
                              json={'expected_revision': 2, 'value': bad}).status_code == 422


@pytest.fixture
def profiles_restored(store):
    yield
    # The Accounts database is shared by every test: put the seeded profiles back.
    with store.connect_accounts() as conn:
        conn.execute('DELETE FROM demo_profiles')
        for p in ORIGINAL_PROFILES:
            conn.execute('INSERT INTO demo_profiles (id, display_name, selections) VALUES (%s,%s,%s)',
                         (p['id'], p['display_name'], Jsonb(p['selections'])))


def test_profiles_editor_adds_edits_and_removes_with_revision_checks(store, profiles_restored):
    with Running(store) as run:
        first = run.client.get('/dev/profiles')
        body, tag = first.json(), first.headers['etag']
        assert body['profiles'] == ORIGINAL_PROFILES
        assert run.client.get('/dev/profiles', headers={'If-None-Match': tag}).status_code == 304
        removed = start(run.client, profile='united-casual')['session_token']
        edited = [{**ORIGINAL_PROFILES[1], 'display_name': 'Blues analyst'}, ORIGINAL_PROFILES[0],
                  {'id': 'away-experienced', 'display_name': 'Away regular', 'selections': {'team': 'away', 'fan_style': 'experienced'}}]
        saved = run.client.put('/dev/profiles', json={'expected_revision': body['revision'], 'profiles': edited})
        assert saved.status_code == 200 and saved.json() == {
            'revision': body['revision'] + 1, 'profiles': sorted(edited, key=lambda p: p['id'])}
        assert [p['id'] for p in run.client.get('/product/profiles').json()['profiles']] == [
            'away-experienced', 'neutral-simple', 'riverton-analytical']
        # Stale revision or ETag: refused, nothing written.
        assert run.client.put('/dev/profiles', json={'expected_revision': body['revision'], 'profiles': edited}).status_code == 409
        assert run.client.put('/dev/profiles', json={'profiles': edited}, headers={'If-Match': tag}).status_code == 409
        assert run.client.put('/dev/profiles', json={'profiles': edited}).status_code == 428
        fresh = run.client.get('/dev/profiles').headers['etag']
        assert run.client.put('/dev/profiles', json={'profiles': edited}, headers={'If-Match': fresh}).status_code == 200
        # A session of a removed profile is refused until the viewer chooses another.
        response = run.client.get(path(removed))
        assert response.status_code == 409 and response.json()['code'] == 'profile_not_found'
        assert start(run.client, profile='away-experienced')['audience']['bucket_id'] == 'away:casual'


def test_profiles_follow_renamed_layers(store, profiles_restored):
    """Profiles hold a selection map, so a default template with other layer ids needs no schema change."""
    with Running(store) as run:
        template = run.client.get('/dev/fixtures/default/audience-config').json()
        config = template['config']
        config['layers'][0]['id'] = 'side'
        for bucket in config['buckets']:
            bucket['selections'] = {('side' if k == 'team' else k): v for k, v in bucket['selections'].items()}
        assert run.client.put('/dev/fixtures/default/audience-config',
                              json={'expected_revision': template['revision'], 'config': config}).status_code == 200
        revision = run.client.get('/dev/profiles').json()['revision']
        renamed = [{**p, 'selections': {('side' if k == 'team' else k): v for k, v in p['selections'].items()}}
                   for p in ORIGINAL_PROFILES]
        assert run.client.put('/dev/profiles', json={'expected_revision': revision, 'profiles': renamed}).status_code == 200
        data = start(run.client, profile='united-casual')
        assert data['audience'] == {'bucket_id': 'away:casual',
                                    'selections': {'side': 'away', 'fan_style': 'casual', 'length': 'standard'}}
        # The supported team comes from the option's `{away}` label, not from a layer named `team`.
        assert data['snapshot']['profile']['team'] != 'neutral'


@pytest.mark.parametrize('profiles', [
    [], [{'id': 'Bad Id', 'display_name': 'x', 'selections': {'team': 'home', 'fan_style': 'simple'}}],
    [{'id': 'a', 'display_name': '', 'selections': {'team': 'home', 'fan_style': 'simple'}}],
    [{'id': 'a', 'display_name': 'A', 'selections': {'team': 'home', 'fan_style': 'simple'}}] * 2,
    [{'id': 'a', 'display_name': 'A', 'team': 'home'}],  # the old shape
    [{'id': 'a', 'display_name': 'A', 'selections': {'side': 'home'}}],  # not a layer of the default template
    # Options the default audience template does not define.
    [{'id': 'a', 'display_name': 'A', 'selections': {'team': 'hmoe', 'fan_style': 'simple'}}],
    [{'id': 'a', 'display_name': 'A', 'selections': {'team': 'home', 'fan_style': 'expert'}}]])
def test_invalid_profiles_are_refused(store, profiles):
    with Running(store) as run:
        revision = run.client.get('/dev/profiles').json()['revision']
        assert run.client.put('/dev/profiles', json={'expected_revision': revision, 'profiles': profiles}).status_code == 422
        assert run.client.get('/dev/profiles').json()['profiles'] == ORIGINAL_PROFILES
