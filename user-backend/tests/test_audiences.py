from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend.app import create_app

PATH = '/matches/synthetic-demo/audience-config'
EDIT = '/dev' + PATH


def config(client):
    response = client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    return response, {'expected_revision': body['revision'],
                      'config': {key: body[key] for key in ('layers', 'buckets')}}


def test_catalogue_has_all_twelve_targets_without_any_viewers_or_model(client, monkeypatch):
    from backend.adapters.llm import LocalJsonModel
    def forbidden(*args, **kwargs):
        raise AssertionError('Audience configuration must not invoke a model')
    monkeypatch.setattr(LocalJsonModel, 'complete', forbidden)
    response, _ = config(client)
    body = response.json()
    assert body['schema_version'] == 1 and body['revision'] == 1
    assert len(body['buckets']) == len(body['generation_targets']) == 12
    target = next(t for t in body['generation_targets'] if t['bucket_id'] == 'home:simple')
    assert target['selections'] == {'team': 'home', 'fan_style': 'simple'}
    assert target['layers'][0]['option']['id'] == 'home'
    assert target['layers'][0]['description'] and target['layers'][0]['option']['description']
    assert 'profiles' not in body


def test_etag_conditional_reads_and_description_updates(client):
    before, update = config(client)
    tag = before.headers['etag']
    for header in (tag, 'W/' + tag, '"another", ' + tag, '*'):
        response = client.get(PATH, headers={'If-None-Match': header})
        assert response.status_code == 304 and response.content == b''
    update['config']['layers'][0]['options'][0]['description'] = 'Explain from the home supporter perspective.'
    assert client.put(EDIT, json=update).json()['revision'] == 2
    after = client.get(PATH, headers={'If-None-Match': tag})
    assert after.status_code == 200 and after.headers['etag'] != tag
    assert after.json()['generation_targets'][0]['layers'][0]['option']['description'].startswith('Explain')


def test_new_layer_and_option_and_reduced_generation(client):
    _, update = config(client)
    update['config']['layers'].append({'id': 'language', 'description': 'Narrative language',
        'options': [{'id': 'english', 'description': 'Use English'},
                    {'id': 'spanish', 'description': 'Use Spanish'}]})
    for bucket in update['config']['buckets']:
        bucket['selections']['language'] = 'spanish'
        bucket['enabled'] = bucket['id'] == 'home:simple'
    assert client.put(EDIT, json=update).status_code == 200
    body = client.get(PATH).json()
    assert len(body['buckets']) == 12 and len(body['generation_targets']) == 1
    target = body['generation_targets'][0]
    assert target['layers'][-1]['option'] == {'id': 'spanish', 'description': 'Use Spanish'}
    assert target['selections']['language'] == 'spanish'


def test_invalid_references_and_duplicate_combinations_leave_db_unchanged(client):
    initial, update = config(client)
    update['config']['buckets'][0]['selections']['team'] = 'missing'
    assert client.put(EDIT, json=update).status_code == 422
    _, update = config(client)
    update['config']['buckets'][1]['selections'] = update['config']['buckets'][0]['selections']
    assert client.put(EDIT, json=update).status_code == 422
    assert client.get(PATH).json() == initial.json()


def test_optimistic_updates_prevent_overwriting_another_edit(client):
    _, update = config(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.put(EDIT, json=update), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert client.get(PATH).json()['revision'] == 2


def test_restart_preserves_configuration_and_read_api_has_no_write_operation(client, store):
    _, update = config(client)
    update['config']['buckets'] = []
    assert client.put(EDIT, json=update).status_code == 200
    with TestClient(create_app(store)) as restarted:
        body = restarted.get(PATH).json()
        assert body['revision'] == 2 and body['generation_targets'] == []
        assert restarted.put(EDIT, json=update).status_code == 404
        assert restarted.put(PATH, json=update).status_code == 405
        assert restarted.post('/dev/neutral-narratives', json={}).status_code == 404


def test_unknown_match_does_not_expose_or_overwrite_demo_catalogue(client):
    _, update = config(client)
    assert client.get(PATH.replace('synthetic-demo', 'other')).status_code == 404
    assert client.put(EDIT.replace('synthetic-demo', 'other'), json=update).status_code == 404
    assert client.get(PATH).json()['revision'] == 1
