"""Model per role (PLAN.md §12 M10) and the length layer (M12), migration 047."""
import importlib.util
from pathlib import Path

import pytest

from backend.adapters.llm import role_model, set_role_models
from backend.models.audiences import AudienceConfig
from backend.models.config import CONFIGS

MIGRATION = Path(__file__).resolve().parents[1] / 'migrations' / '047_model_roles_length_layer.py'
spec = importlib.util.spec_from_file_location('m047', MIGRATION)
m047 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m047)


@pytest.fixture(autouse=True)
def reset():
    yield
    set_role_models({})


def test_seeded_roles_keep_each_services_own_model(monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_EFFORT', 'low')
    roles = CONFIGS['models'].model_validate(m047.MODELS)
    set_role_models(roles.backend.model_dump())
    assert role_model('match_question', 'env-model') == ('env-model', 'low')


def test_a_set_deployment_moves_only_its_role(monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_EFFORT', 'low')
    roles = {**m047.MODELS['backend'], 'replay': {'deployment': 'gpt-5-mini', 'effort': ''}}
    set_role_models(CONFIGS['models'].model_validate({**m047.MODELS, 'backend': roles}).backend.model_dump())
    # No effort keeps this deployment's: Foundry models reject the chat call's temperature 0.
    assert role_model('match_replay', 'env-model') == ('gpt-5-mini', 'low')
    assert role_model('subscription_planner', 'env-model') == ('env-model', 'low')
    roles['replay']['effort'] = 'high'
    set_role_models(CONFIGS['models'].model_validate({**m047.MODELS, 'backend': roles}).backend.model_dump())
    assert role_model('match_replay', 'env-model') == ('gpt-5-mini', 'high')


def test_a_set_deployment_without_any_effort_is_a_chat_model(monkeypatch):
    monkeypatch.delenv('LOCAL_LLM_EFFORT', raising=False)
    roles = {**m047.MODELS['backend'], 'replay': {'deployment': 'local-chat', 'effort': ''}}
    set_role_models(CONFIGS['models'].model_validate({**m047.MODELS, 'backend': roles}).backend.model_dump())
    assert role_model('match_replay', 'env-model') == ('local-chat', None)


def test_roles_reject_unknown_efforts_and_odd_names():
    bad = {**m047.MODELS, 'backend': {**m047.MODELS['backend'], 'questions': {'deployment': 'a b', 'effort': ''}}}
    with pytest.raises(ValueError):
        CONFIGS['models'].model_validate(bad)
    bad = {**m047.MODELS, 'engine': {**m047.MODELS['engine'], 'author': {'deployment': 'x', 'effort': 'max'}}}
    with pytest.raises(ValueError):
        CONFIGS['models'].model_validate(bad)


TEMPLATE = {'layers': [
    {'id': 'team', 'description': 'Side.', 'options': [{'id': 'home', 'description': 'Home.'},
                                                        {'id': 'away', 'description': 'Away.'}]},
    {'id': 'fan_style', 'description': 'Style.', 'options': [{'id': 'casual', 'description': 'Casual.'}]}],
    'buckets': [{'id': 'home:casual', 'selections': {'team': 'home', 'fan_style': 'casual'}, 'enabled': True},
                {'id': 'away:casual', 'selections': {'team': 'away', 'fan_style': 'casual'}, 'enabled': False}]}


def test_length_layer_keeps_existing_buckets_and_adds_disabled_brief_twins():
    document = m047.with_length(TEMPLATE)
    AudienceConfig.model_validate(document)  # every bucket selects every layer, no duplicate combinations
    assert [b['id'] for b in document['buckets']] == ['home:casual', 'away:casual', 'home:casual:brief',
                                                      'away:casual:brief']
    assert document['buckets'][0] == {**TEMPLATE['buckets'][0], 'selections': {
        'team': 'home', 'fan_style': 'casual', 'length': 'standard'}}
    assert not any(b['enabled'] for b in document['buckets'][2:])
    assert m047.with_length(document) is None  # applied once


def test_the_brief_option_reaches_the_author_through_the_bucket_framing():
    document = m047.with_length(TEMPLATE)
    document['buckets'][2]['enabled'] = True
    target = next(t for t in AudienceConfig.model_validate(document).targets() if t['bucket_id'] == 'home:casual:brief')
    length = next(layer for layer in target['layers'] if layer['id'] == 'length')
    assert length['option']['description'] == m047.LENGTH['options'][1]['description']
