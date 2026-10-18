"""Comparison mechanics only; live models remain an opt-in benchmark."""
import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from backend.adapters.llm import LocalJsonModel
from benchmarks.model_observer import ModelObserver, pin_verification, response_metadata
from benchmarks import model_strength as strength


def test_observer_real_sdk_reusable_after_client_close():
    def respond(request):
        assert request.headers['cache-control'] == 'no-cache'
        assert json.loads(request.content)['model'] == 'requested-model'
        return httpx.Response(200, json={
            'id': 'synthetic', 'object': 'chat.completion', 'created': 1,
            'model': 'reported-model', 'usage': {'prompt_tokens': 10, 'completion_tokens': 5,
                                               'total_tokens': 15, 'estimated': True},
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': '{"ok":true}'}}]})
    observer = ModelObserver(transport_factory=lambda: httpx.MockTransport(respond))
    model = LocalJsonModel('http://local.invalid/v1', 'requested-model', 'never-save-secret', transport=observer)

    async def twice():
        for _ in range(2):
            assert await model.complete('JSON only', {'request': 'synthetic'}) == {'ok': True}
    asyncio.run(twice())
    assert len(observer.calls) == 2
    assert all(call['status'] == 'ok' and call['request_bytes'] > 0 for call in observer.calls)
    assert all(call['tokens']['estimated'] is True for call in observer.calls)
    assert pin_verification(observer.calls, ['reported-model'])['pin_verified']
    saved = json.dumps(observer.calls)
    assert 'never-save-secret' not in saved and 'local.invalid' not in saved and 'JSON only' not in saved


def test_response_metadata_sse_and_no_content_retention():
    models, usage = response_metadata(b'data: {"model":"one","choices":[{"text":"secret"}]}\n\ndata: {"model":"one","usage":{"total_tokens":42,"estimated":false}}\n\ndata: [DONE]\n')
    assert models == ['one']
    assert usage == {'total_tokens': 42, 'estimated': False}
    assert response_metadata(b'{"model":"https://private.invalid","usage":{"total_tokens":-3}}') == ([], {})


@pytest.mark.parametrize('calls,reason', [
    ([], 'model_not_invoked'),
    ([{'status': 'http_error', 'actual_models': []}], 'no_successful_model_response'),
    ([{'status': 'ok', 'actual_models': []}], 'missing_returned_model_identity'),
    ([{'status': 'ok', 'actual_models': ['wrong']}, {'status': 'ok', 'actual_models': ['right']}], 'unexpected_model_substitution'),
])
def test_missing_or_substituted_identity_never_passes(calls, reason):
    pin = pin_verification(calls, ['right'])
    assert not pin['pin_verified'] and pin['pin_reason'] == reason


def test_http_failure_then_expected_model_can_verify():
    assert pin_verification([{'status': 'http_error', 'actual_models': []},
                             {'status': 'ok', 'actual_models': ['right']}], ['right'])['pin_verified']


def test_config_strict_and_no_endpoints(tmp_path):
    path = tmp_path / 'models.json'
    valid = {'label': 'small', 'model': 'requested', 'expected_models': ['reported']}
    path.write_text(json.dumps({'models': [valid]}))
    assert strength.load_models(path) == [valid]
    for invalid in ({**valid, 'model': 'http://private.invalid'}, {**valid, 'expected_models': []},
                    {**valid, 'secret': 'do-not-store'}):
        path.write_text(json.dumps({'models': [invalid]}))
        with pytest.raises(ValueError):
            strength.load_models(path)


def test_pair_alternation_sequential_models_and_substitution():
    calls = []
    configs = [{'label': label, 'model': label, 'expected_models': ['right']} for label in ('a', 'b')]
    cases = [{'id': str(n), 'quality': 'clear'} for n in range(2)]
    def build(config, variant, timeout, observer, candidate_instructions=None):
        calls.append((config['label'], variant))
        observer.calls.append({'status': 'ok', 'actual_models': ['wrong' if config['label'] == 'b' else 'right']})
        return None, {'prompt_sha256': variant, 'schema_sha256': variant}
    async def evaluate(workflow, case, context, callback):
        return {'id': case['id'], 'ok': True, 'seconds': 0.1}
    args = SimpleNamespace(concurrency=1, suite_timeout=3, case_timeout=1)
    with patch.object(strength, 'build_workflow', build), patch.object(strength, 'evaluate_conversation', evaluate):
        rows = asyncio.run(strength.compare(args, configs, cases, {'match_id':'m','players':[],'teams':[]}, [], io.StringIO()))
    assert calls == [(label, variant) for label in ('a', 'b') for pair in
                     (('baseline', 'current'), ('current', 'baseline')) for variant in pair]
    assert all(row['interpretation_ok'] for row in rows)
    assert sum(row['ok'] for row in rows) == 4


def test_suite_timeout_cancels_workers_and_records_unmeasured():
    cancelled = []
    def build(config, variant, timeout, observer, candidate_instructions=None):
        return None, {}
    async def evaluate(*args):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    args = SimpleNamespace(concurrency=1, suite_timeout=0.01, case_timeout=1)
    configs = [{'label':'a','model':'a','expected_models':['a']}]
    cases = [{'id':'one','quality':'clear'}, {'id':'two','quality':'clear'}]
    with patch.object(strength, 'build_workflow', build), patch.object(strength, 'evaluate_conversation', evaluate):
        rows = asyncio.run(strength.compare(args, configs, cases, {'match_id':'m','players':[],'teams':[]}, [], io.StringIO()))
    assert cancelled == [True]
    assert len(rows) == 4 and all(row['reason'] == 'suite_timeout_unmeasured' for row in rows)


@pytest.mark.parametrize('variants,expected', [(['current'], [('current',), ('current',)]),
    (['baseline'], [('baseline',), ('baseline',)]),
    (['current', 'baseline'], [('baseline', 'current'), ('current', 'baseline')])])
def test_variant_filter_preserves_alternation(variants, expected):
    assert [strength.variant_order(index, variants) for index in range(2)] == expected


def test_single_variant_reads_frozen_prompt_once_and_no_other_rows(tmp_path):
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('Frozen instructions')
    calls = []
    def build(config, variant, timeout, observer, candidate_instructions=None):
        calls.append((variant, candidate_instructions))
        prompt.write_text('Changed while running')
        observer.calls.append({'status': 'ok', 'actual_models': ['right']})
        return None, {'prompt_sha256': 'hash'}
    async def evaluate(workflow, case, context, callback):
        return {'id': case['id'], 'ok': True}
    args = SimpleNamespace(concurrency=1, suite_timeout=2, case_timeout=1,
                           variants=['current'], candidate_prompt=prompt)
    with patch.object(strength, 'build_workflow', build), patch.object(strength, 'evaluate_conversation', evaluate):
        rows = asyncio.run(strength.compare(args, [{'label':'a','model':'a','expected_models':['right']}],
            [{'id':'1','quality':'clear'}, {'id':'2','quality':'clear'}],
            {'match_id':'m','players':[],'teams':[]}, [], io.StringIO()))
    assert calls == [('current', 'Frozen instructions')] * 2
    assert len(rows) == 2 and all(row['variant'] == 'current' for row in rows)


def test_candidate_override_keeps_compact_contract(monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_BASE_URL', 'http://local.invalid/v1')
    with patch.object(strength, 'GoalAgent') as agent, patch.object(strength, 'RuleWorkflow'):
        agent.return_value.instructions = 'candidate'
        agent.return_value.schema = {'type':'object'}
        strength.build_workflow({'model':'test'}, 'current', 1, ModelObserver(), 'candidate')
    assert agent.call_args.kwargs == {'instructions':'candidate', 'compact_contract':True}
