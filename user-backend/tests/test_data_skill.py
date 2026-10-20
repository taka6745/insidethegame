"""Data knowledge must match the active adapter, without evaluation answers."""
import asyncio
import json
from pathlib import Path
from enum import Enum
from typing import Literal

import pytest
from pydantic import Field

from backend.adapters.events import OptaInspiredAdapter
from backend.adapters.feed_reference import FeedReference
from backend.agents.data_skill import EventDataSkill
from backend.agents.orchestrator import GoalAgent
from backend.agents.settings import AgentSettings
from backend.agents.workflow import workflow_from_env
from backend.models.events import Event
from benchmarks.model_strength import build_workflow
from benchmarks.model_observer import ModelObserver


def profile():
    return FeedReference.load(Path(__file__).parents[1] /
                              'backend/adapters/feed_profiles/opta-inspired-v1.json')


def test_reference_types_follow_current_schema_without_copied_enums():
    class UpdatedClock(Event):
        match_time_seconds: int = Field(ge=0, le=15000)
    before, after = profile().describe(), profile().describe(UpdatedClock)
    assert after['fields']['match_time_seconds']['schema']['maximum'] == 15000
    assert before['schema_sha256'] != after['schema_sha256']
    assert set(before['fields']) == set(Event.model_fields)


def test_new_fields_and_event_categories_require_semantic_review():
    class NewField(Event):
        recipient_id: str | None = None
    class NewEvent(Event):
        event_type: Literal['new_action']
    for model in (NewField, NewEvent):
        with pytest.raises(ValueError, match='review the profile'):
            profile().describe(model)


def test_referenced_enum_schema_is_self_contained():
    class Part(str, Enum):
        HEAD = 'head'
        FOOT = 'foot'
    class EnumEvent(Event):
        body_part: Part | None = None
    field = profile().describe(EnumEvent)['fields']['body_part']['schema']
    assert '$ref' not in json.dumps(field)
    assert field['anyOf'][0]['enum'] == ['head', 'foot']


def test_recursive_field_schema_requires_explicit_support():
    from pydantic import BaseModel
    class Node(BaseModel):
        next: 'Node | None' = None
    class RecursiveEvent(Event):
        body_part: Node | None = None
    with pytest.raises(ValueError, match='Recursive or external'):
        profile().describe(RecursiveEvent)


def test_profile_replacement_reaches_model_without_old_feed_mapping():
    reference = profile().model_copy(update={'contract_id':'alternate-normalized-v2',
                                             'events':dict(profile().events, corner='Corner taken, not awarded.')}).describe()
    seen = []
    class Capture:
        async def complete(self, system, payload):
            seen.append((system, payload))
            return {'status':'unsupported','message':'Test capture'}
    skill = EventDataSkill(reference)
    reference['events']['corner'] = 'external mutation'
    agent = GoalAgent(Capture(), data_skill=skill)
    asyncio.run(agent.define('Count corners', {'match_id':'different-match', 'players':[], 'teams':[]}))
    system, payload = seen[0]
    assert 'METRIC MAPPING' not in system
    assert payload['data_skill']['feed_reference']['events']['corner'] == 'Corner taken, not awarded.'
    assert payload['data_skill']['feed_reference']['contract_id'] == 'alternate-normalized-v2'
    assert 'request' not in payload['data_skill']
    payload['data_skill']['feed_reference']['events']['corner'] = 'mutated'
    assert skill.context()['feed_reference']['events']['corner'] == 'Corner taken, not awarded.'


def test_reference_exposes_no_raw_event_records_or_match_catalogue():
    content = EventDataSkill(OptaInspiredAdapter().data_reference()).context()
    text = json.dumps(content)
    for forbidden in ('expected_weights', 'expected_status', 'filter-lab-match', 'mbappe',
                      'balanced-', 'data-transfer-', 'presets', 'delivery_index'):
        assert forbidden not in text.lower()
    assert set(content['feed_reference']) == {'contract_id', 'schema_sha256', 'provenance',
                                             'fields', 'events', 'guarantees', 'unavailable'}


def test_data_skill_setting_requires_active_adapter(monkeypatch):
    monkeypatch.setenv('LOCAL_LLM_MODE', 'local')
    monkeypatch.setenv('AGENT_DATA_SKILL', 'feed')
    with pytest.raises(ValueError, match='active event adapter'):
        workflow_from_env()
    monkeypatch.setenv('LOCAL_LLM_BASE_URL', 'http://local.invalid/v1')
    monkeypatch.setenv('LOCAL_LLM_MODEL', 'mock')
    workflow = workflow_from_env(data_reference=OptaInspiredAdapter().data_reference())
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
    original = OptaInspiredAdapter().data_reference()
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
    seen[0]['events']['touch'] = 'mutated by request'
    assert replacement['events']['touch'] == original['events']['touch']
