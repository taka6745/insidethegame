"""Data knowledge must match the SPADL action model, without evaluation answers."""
import asyncio
import json
from pathlib import Path

import pytest
from pydantic import Field

from typing import get_args

from backend.adapters.feed_reference import FeedReference
from backend.adapters.match_reference import data_reference
from backend.models.actions import ActionType, SpadlAction
from backend.agents.data_skill import EventDataSkill
from backend.agents.orchestrator import GoalAgent
from backend.agents.settings import AgentSettings
from backend.agents.workflow import workflow_from_env
from benchmarks.model_strength import build_workflow
from benchmarks.model_observer import ModelObserver


def profile():
    return FeedReference.load()


def test_reference_follows_the_action_model_and_spadl_enums():
    reference = profile().describe()
    assert set(reference['fields']) == set(SpadlAction.model_fields)
    assert set(reference['events']) == set(get_args(ActionType))
    class UpdatedClock(SpadlAction):
        match_time_seconds: int = Field(ge=0, le=15000)
    assert profile().describe(UpdatedClock)['schema_sha256'] != reference['schema_sha256']


def test_new_fields_require_semantic_review():
    class NewField(SpadlAction):
        recipient_id: str | None = None
    with pytest.raises(ValueError, match='review the profile'):
        profile().describe(NewField)
    missing = profile().model_copy(update={'events': {k: v for k, v in profile().events.items() if k != 'dribble'}})
    with pytest.raises(ValueError, match='review the profile'):
        missing.describe()


def test_profile_replacement_reaches_model_without_old_feed_mapping():
    reference = profile().model_copy(update={'contract_id':'alternate-normalized-v2',
                                             'events':dict(profile().events, corner_short='Corner taken, not awarded.')}).describe()
    seen = []
    class Capture:
        async def complete(self, system, payload):
            seen.append((system, payload))
            return {'status':'unsupported','message':'Test capture'}
    skill = EventDataSkill(reference)
    reference['events']['corner_short'] = 'external mutation'
    agent = GoalAgent(Capture(), data_skill=skill)
    asyncio.run(agent.define('Count corners', {'match_id':'different-match', 'players':[], 'teams':[]}))
    system, payload = seen[0]
    assert 'METRIC MAPPING' not in system
    assert payload['data_skill']['feed_reference']['events']['corner_short'] == 'Corner taken, not awarded.'
    assert payload['data_skill']['feed_reference']['contract_id'] == 'alternate-normalized-v2'
    assert 'request' not in payload['data_skill']
    payload['data_skill']['feed_reference']['events']['corner_short'] = 'mutated'
    assert skill.context()['feed_reference']['events']['corner_short'] == 'Corner taken, not awarded.'


def test_reference_exposes_no_raw_event_records_or_match_catalogue():
    content = EventDataSkill(data_reference(None)).context()
    text = json.dumps(content)
    for forbidden in ('expected_weights', 'expected_status', 'filter-lab-match', 'mbappe',
                      'balanced-', 'data-transfer-', 'presets', 'delivery_index'):
        assert forbidden not in text.lower()
    assert set(content['feed_reference']) == {'contract_id', 'schema_sha256', 'provenance', 'fields', 'derived',
                                             'events', 'results', 'bodyparts', 'zones', 'families',
                                             'outside_spadl', 'guarantees', 'unavailable'}


def test_data_skill_setting_requires_active_adapter(monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_MODE', 'local')
    monkeypatch.setenv('AGENT_DATA_SKILL', 'feed')
    monkeypatch.setenv('LOCAL_LLM_BASE_URL', 'http://local.invalid/v1')
    monkeypatch.setenv('LOCAL_LLM_MODEL', 'mock')
    with pytest.raises(ValueError, match='active event adapter'):
        workflow_from_env()
    workflow = workflow_from_env(data_reference=data_reference(None))
    assert workflow.orchestrator.data_skill is not None
    monkeypatch.setenv('AGENT_DATA_SKILL', 'unknown')
    with pytest.raises(ValueError, match='AGENT_DATA_SKILL'):
        AgentSettings.from_env()


def test_paired_variants_change_data_knowledge_not_output_schema(monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_BASE_URL', 'http://local.invalid/v1')
    for without, with_skill in [('current','skill'), ('schema','schema_skill'),
                                ('current','skill_added'), ('schema','schema_skill_added')]:
        old, old_meta = build_workflow({'model':'mock'}, without, 10, ModelObserver())
        new, new_meta = build_workflow({'model':'mock'}, with_skill, 10, ModelObserver())
        assert old_meta['schema_sha256'] == new_meta['schema_sha256']
        assert old.orchestrator.data_skill is None
        assert len(new_meta['data_skill_sha256']) == 64
        assert new.orchestrator.response_mode == old.orchestrator.response_mode
        if with_skill.endswith('_added'):
            assert old_meta['prompt_sha256'] == new_meta['prompt_sha256']


def test_request_reference_replaces_startup_skill_without_leaking_between_requests():
    original = data_reference(None)
    replacement = {**original, 'contract_id': 'replacement-feed'}
    seen = []
    class Capture:
        async def complete(self, system, payload):
            seen.append(payload['data_skill']['feed_reference'])
            return {'status': 'unsupported', 'message': 'Test capture'}
    agent = GoalAgent(Capture(), data_skill=EventDataSkill(original))
    async def run():
        await agent.define('Count touches', {'match_id':'m', 'data_reference':replacement})
        await agent.define('Count touches', {'match_id':'m'})
    asyncio.run(run())
    assert seen[0]['contract_id'] == 'replacement-feed'
    assert seen[1]['contract_id'] == original['contract_id']
    seen[0]['events']['dribble'] = 'mutated by request'
    assert replacement['events']['dribble'] == original['events']['dribble']
