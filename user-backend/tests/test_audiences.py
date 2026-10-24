"""Audience templates per fixture (configuration) and the catalogue each match serves the engine."""
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend.app import create_app
from harness import MATCH, build

PATH = f'/matches/{MATCH}/audience-config'
TEMPLATE = '/dev/fixtures/riverton-madrid/audience-config'


def started(store, *matches):
    app, upstream, _ = build(store)
    client = TestClient(app).__enter__()
    for match_id in matches or (MATCH,):
        upstream.add(match_id)
        client.portal.call(upstream.kickoff, app.state.registry, match_id)
    return client, upstream


def template(client, fixture='riverton-madrid'):
    body = client.get(f'/dev/fixtures/{fixture}/audience-config').json()
    return {'expected_revision': body['revision'], 'config': body['config']}


DEMO_BUCKETS = ['home:analytical', 'away:casual', 'neutral:simple', 'neutral:simple:brief']


def enabled(update, bucket_ids):
    for bucket in update['config']['buckets']:
        bucket['enabled'] = bucket['id'] in bucket_ids
    return update


def test_new_match_serves_all_twelve_definitions_and_only_enabled_targets_without_model(store, monkeypatch):
    from backend.adapters.llm import LocalJsonModel
    monkeypatch.setattr(LocalJsonModel, 'complete', lambda *a, **k: (_ for _ in ()).throw(AssertionError('no model')))
    client, _ = started(store)
    body = client.get(PATH).json()
    assert body['schema_version'] == 1 and body['match_id'] == MATCH and body['revision'] == 1
    # 12 team × style buckets, each with a disabled Brief twin (the length layer, migration 047).
    assert len(body['buckets']) == 24 and 'profiles' not in body
    # The unedited default enables the demo profiles' buckets (migration 018); viewers enable nothing.
    targets = body['generation_targets']
    assert sorted(t['bucket_id'] for t in targets) == sorted(DEMO_BUCKETS)
    # Engine shape (narrative_engine/audience/targets.py): every layer's and option's description.
    target = next(t for t in targets if t['bucket_id'] == 'home:analytical')
    assert target['selections'] == {'team': 'home', 'fan_style': 'analytical', 'length': 'standard'}
    assert [(layer['id'], layer['option']['id']) for layer in target['layers']] == [('team', 'home'), ('fan_style', 'analytical'),
                                                                                        ('length', 'standard')]
    assert all(layer['description'] and layer['option']['description'] for layer in target['layers'])
    assert body['layers'][0]['options'][0]['label'] == '{home}' and body['layers'][1]['options'][0]['label'] == 'Simple'
    client.__exit__(None, None, None)


def test_unknown_match_is_404_and_purged_match_is_gone(store):
    client, _ = started(store)
    assert client.get('/matches/other-00000000/audience-config').status_code == 404
    assert client.get(PATH).status_code == 200
    assert client.post('/admin/matches/purge', json={'match_id': MATCH}).status_code == 200
    assert client.get(PATH).status_code == 404
    client.__exit__(None, None, None)


def test_enabled_flags_choose_targets_for_every_match_of_the_fixture(store):
    client, _ = started(store, MATCH, 'riverton-madrid-99999999', 'other-fixture-11111111')
    tag = client.get(PATH).headers['etag']
    update = enabled(template(client), ['home:simple'])
    revision = update['expected_revision']
    assert client.put(TEMPLATE, json=update).json() == {'revision': revision + 1}
    for match_id in (MATCH, 'riverton-madrid-99999999'):
        body = client.get(f'/matches/{match_id}/audience-config').json()
        assert [t['bucket_id'] for t in body['generation_targets']] == ['home:simple']
        # A catalogue is copied on first read: the already-read match moved to revision 2.
        assert body['revision'] == (2 if match_id == MATCH else 1)
    # Another fixture keeps the default template.
    other = client.get('/matches/other-fixture-11111111/audience-config').json()
    assert sorted(t['bucket_id'] for t in other['generation_targets']) == sorted(DEMO_BUCKETS)
    assert client.get(PATH, headers={'If-None-Match': tag}).status_code == 200
    assert client.put(TEMPLATE, json=update).status_code == 409  # Stale revision.
    listing = client.get('/dev/audience-templates').json()
    assert {'fixture': 'riverton-madrid', 'revision': revision + 1} in listing['templates']
    assert {'match_id': MATCH, 'fixture': 'riverton-madrid', 'revision': 2, 'enabled': ['home:simple']} in listing['matches']
    client.__exit__(None, None, None)


def test_editing_back_to_the_default_inherits_it_again(store):
    client, _ = started(store)
    original = template(client)
    assert client.get(TEMPLATE).json()['inherited'] is True
    revision = client.put(TEMPLATE, json=enabled(template(client), ['home:simple'])).json()['revision']
    assert client.get(TEMPLATE).json()['inherited'] is False
    # Restoring the default's flags leaves no copy of the default behind.
    restored = {'expected_revision': revision, 'config': original['config']}
    assert client.put(TEMPLATE, json=restored).json() == {'revision': original['expected_revision']}
    assert client.get(TEMPLATE).json()['inherited'] is True
    assert [t['fixture'] for t in client.get('/dev/audience-templates').json()['templates']] == ['default']
    assert sorted(t['bucket_id'] for t in client.get(PATH).json()['generation_targets']) == sorted(DEMO_BUCKETS)
    client.__exit__(None, None, None)


def test_layers_options_and_buckets_can_be_added_and_removed(store):
    client, _ = started(store)
    update = template(client)
    update['config']['layers'] = [update['config']['layers'][1]]
    update['config']['layers'][0]['options'].append({'id': 'tactical', 'label': 'Tactics', 'description': 'Shape and pressing.'})
    update['config']['buckets'] = [{'id': o['id'], 'selections': {'fan_style': o['id']}, 'enabled': o['id'] == 'tactical'}
                                   for o in update['config']['layers'][0]['options']]
    assert client.put(TEMPLATE, json=update).status_code == 200
    body = client.get(PATH).json()
    assert [layer['id'] for layer in body['layers']] == ['fan_style'] and len(body['buckets']) == 5
    assert body['generation_targets'] == [{'bucket_id': 'tactical', 'selections': {'fan_style': 'tactical'}, 'layers': [
        {'id': 'fan_style', 'description': body['layers'][0]['description'],
         'option': {'id': 'tactical', 'description': 'Shape and pressing.', 'label': 'Tactics'}}]}]
    client.__exit__(None, None, None)


def test_any_layer_can_back_a_team_by_reference(store):
    client, _ = started(store)
    update = template(client)
    update['config']['layers'] = [{'id': 'side', 'description': 'Allegiance.', 'options': [
        {'id': 'blues', 'label': 'Blues', 'team': 'home', 'description': 'Backs the home side.'},
        {'id': 'bad', 'label': 'Bad', 'team': 'neutral', 'description': 'Rejected.'}]}]
    update['config']['buckets'] = [{'id': 'blues', 'selections': {'side': 'blues'}, 'enabled': True}]
    assert client.put(TEMPLATE, json=update).status_code == 422
    update['config']['layers'][0]['options'].pop()
    assert client.put(TEMPLATE, json=update).status_code == 200
    option = client.get(PATH).json()['generation_targets'][0]['layers'][0]['option']
    assert option == {'id': 'blues', 'label': 'Blues', 'team': 'home', 'description': 'Backs the home side.'}
    client.__exit__(None, None, None)


def test_etag_and_template_description_edits(store):
    client, _ = started(store)
    before = client.get(PATH)
    tag = before.headers['etag']
    for header in (tag, 'W/' + tag, '"another", ' + tag, '*'):
        assert client.get(PATH, headers={'If-None-Match': header}).status_code == 304
    update = template(client)
    update['config']['layers'][0]['options'][0]['description'] = 'Explain from the home supporter perspective.'
    assert client.put(TEMPLATE, json=update).json()['revision'] == update['expected_revision'] + 1
    after = client.get(PATH, headers={'If-None-Match': tag})
    assert after.status_code == 200 and after.json()['layers'][0]['options'][0]['description'].startswith('Explain')
    client.__exit__(None, None, None)


def test_unchanged_polls_read_only_the_revision(store, monkeypatch):
    from backend.repositories.audiences import AudienceRepository
    client, _ = started(store)
    tag = client.get(PATH).headers['etag']
    original, reads = AudienceRepository.read, []
    monkeypatch.setattr(AudienceRepository, 'read', lambda *args: reads.append(args) or original(*args))
    assert all(client.get(PATH, headers={'If-None-Match': tag}).status_code == 304 for _ in range(5))
    assert reads == []
    client.__exit__(None, None, None)


def test_invalid_templates_and_concurrent_edits(store):
    client, _ = started(store)
    update = template(client)
    update['config']['buckets'][0]['selections']['team'] = 'missing'
    assert client.put(TEMPLATE, json=update).status_code == 422
    update = template(client)
    update['config']['buckets'][1]['selections'] = update['config']['buckets'][0]['selections']
    assert client.put(TEMPLATE, json=update).status_code == 422
    update = template(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.put(TEMPLATE, json=update), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    client.__exit__(None, None, None)


def test_restart_keeps_templates_and_read_api_has_no_write_operation(store):
    client, upstream = started(store)
    update = template(client)
    update['config']['buckets'] = []
    assert client.put(TEMPLATE, json=update).status_code == 200
    assert client.get(PATH).json()['buckets'] == []
    client.__exit__(None, None, None)
    with TestClient(create_app(store, upstream.dab)) as restarted:
        assert restarted.get(PATH).json()['buckets'] == []
        assert restarted.put(TEMPLATE, json=update).status_code == 404
        assert restarted.put(PATH, json=update).status_code == 405
