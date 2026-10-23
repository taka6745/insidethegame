"""Backend-owned prompt store: seeded versions, placeholder guard, optimistic saves and rollback."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.services.prompts import PromptService
from harness import Upstream

SEEDS = Path(__file__).parents[1] / 'migrations/prompts'
ENGINE = Path(__file__).parents[2] / 'narrative-engine/narrative_engine/agents/prompts'


def prompts(client):
    response = client.get('/narrative-prompts')
    assert response.status_code == 200
    return response, {p['role']: p for p in response.json()['prompts']}


def save(client, role, template, expected):
    return client.put(f'/dev/narrative-prompts/{role}', json={'template': template, 'expected_version': expected})


def test_seeds_are_active_with_their_placeholders_and_etag(client):
    response, active = prompts(client)
    assert response.json()['revision'] == 1
    assert set(active) == {'minute-summary', 'context-compression', 'match-analyst', 'narrative-author',
                           'subscription-planner', 'subscription-decision', 'subscription-author'}
    author = active['narrative-author']
    assert author['version'] == 1 and author['template'] == (SEEDS / 'narrative-author.txt').read_text()
    assert author['placeholders'] == ['combined_match_context', 'game_state_statistics', 'key_event_ledger',
                                      'match_events', 'match_trends', 'narrative_excerpts', 'storylines',
                                      'trigger_reason', 'user_type']
    assert active['match-analyst']['placeholders'] == ['analysis_reason', 'combined_match_context', 'confidence_levels',
                                                       'game_state_statistics', 'key_event_ledger', 'match_trends',
                                                       'max_evidence', 'max_observations', 'short_window_levels',
                                                       'short_windows', 'storylines']
    assert 'follows' not in active['subscription-decision']['placeholders']  # no viewer text in the shared state
    assert active['minute-summary']['placeholders'] == ['game_state_statistics', 'match_events']
    tag = response.headers['etag']
    assert client.get('/narrative-prompts', headers={'If-None-Match': tag}).status_code == 304


def test_seed_copies_match_the_engine_sources():
    if not ENGINE.exists():
        return  # The backend image ships only its own fixtures.
    for role, source in (('minute-summary', 'minute-summary.v3'), ('context-compression', 'context-compression.v2'),
                         ('match-analyst', 'match-analyst.v4'), ('match-analyst.v3', 'match-analyst.v3'),
                         ('narrative-author', 'narrative-author.v7'),
                         ('match-analyst.v2', 'match-analyst.v2'), ('match-analyst.v1', 'match-analyst.v1'),
                         ('narrative-author.v5', 'narrative-author.v5'), ('narrative-author.v4', 'narrative-author.v4'),
                         ('subscription-decision', 'subscription-decision.v2'),
                         ('subscription-decision.v1', 'subscription-decision.v1')):
        assert (SEEDS / f'{role}.txt').read_bytes() == (ENGINE / f'{source}.txt').read_bytes()


def test_save_appends_version_and_rollback_reactivates(client):
    before, active = prompts(client)
    template = active['minute-summary']['template'] + '\nBe brief.'
    assert save(client, 'minute-summary', template, 1).json() == {'role': 'minute-summary', 'version': 2}
    after, active = prompts(client)
    assert after.json()['revision'] == 2 and after.headers['etag'] != before.headers['etag']
    assert active['minute-summary']['version'] == 2 and active['minute-summary']['template'] == template
    listing = client.get('/dev/narrative-prompts').json()['roles']
    summary = next(r for r in listing if r['role'] == 'minute-summary')
    assert summary['active_version'] == 2 and [v['version'] for v in summary['versions']] == [2, 1]
    assert [v['source'] for v in summary['versions']] == ['dev', 'seed']
    assert client.post('/dev/narrative-prompts/minute-summary/versions/1/activate').json()['version'] == 1
    rolled, active = prompts(client)
    assert rolled.json()['revision'] == 3 and active['minute-summary']['version'] == 1
    assert client.post('/dev/narrative-prompts/minute-summary/versions/9/activate').status_code == 404


def test_rejections_leave_store_unchanged(client):
    initial, active = prompts(client)
    template = active['narrative-author']['template']
    assert save(client, 'narrative-author', template.replace('{user_type}', 'a fan'), 1).status_code == 422
    assert save(client, 'narrative-author', template + ' {extra}', 1).status_code == 422
    assert save(client, 'narrative-author', template, 2).status_code == 409
    assert save(client, 'narrative-author', 'x' * 20_001, 1).status_code == 422
    assert save(client, 'unknown-role', template, 1).status_code == 422
    # JSON braces in a template are not placeholders.
    assert save(client, 'narrative-author', template + '\n{"summary": "..."}', 1).status_code == 200
    assert save(client, 'narrative-author', template, 1).status_code == 409
    assert client.get('/narrative-prompts').json()['revision'] == initial.json()['revision'] + 1


def test_concurrent_saves_allow_one_winner(client):
    _, active = prompts(client)
    template = active['context-compression']['template']
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda n: save(client, 'context-compression', template + str(n), 1), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]


def test_restart_keeps_versions_and_read_api_has_no_dev_routes(client, store):
    _, active = prompts(client)
    assert save(client, 'minute-summary', active['minute-summary']['template'] + '!', 1).status_code == 200
    with TestClient(create_app(store, Upstream().dab)) as restarted:
        _, active = prompts(restarted)
        assert active['minute-summary']['version'] == 2
        assert restarted.get('/dev/narrative-prompts').status_code == 404
        assert save(restarted, 'minute-summary', 'x', 2).status_code == 404
        assert restarted.get('/dev/pipeline').status_code == 404


def test_pipeline_lists_backend_and_tolerates_missing_upstreams(store):
    app = create_app(store, Upstream().dab, enable_dev_feed=True, upstream_health={'etl': 'http://127.0.0.1:9/health'})
    with TestClient(app) as client:
        services = client.get('/dev/pipeline').json()['services']
    assert services[0] == {'name': 'user-backend', 'status': 'ok'}
    assert services[1]['name'] == 'etl' and services[1]['status'] == 'unavailable'


def test_the_editor_is_given_the_active_versions_placeholders_not_an_older_ones():
    class Versions:  # newest first, as the repository lists them; v1 had fewer placeholders than v2
        def versions(self):
            at = datetime(2026, 10, 22, tzinfo=timezone.utc)
            return {'narrative-author': 2}, [
                {'role': 'narrative-author', 'version': 2, 'template': '{a} {b}', 'placeholders': ['a', 'b'],
                 'source': 'seed', 'created_at': at},
                {'role': 'narrative-author', 'version': 1, 'template': '{a}', 'placeholders': ['a'],
                 'source': 'seed', 'created_at': at}]
    role, = asyncio.run(PromptService(Versions()).versions())['roles']
    assert role['placeholders'] == ['a', 'b'] and [v['version'] for v in role['versions']] == [2, 1]
