"""Provider constraints remain checked locally; a schema is not semantic proof."""
import asyncio
import json

import httpx
import pytest

from backend.adapters.llm import LocalJsonModel, ModelError
from backend.agents.models import Goal
from backend.agents.orchestrator import GoalAgent
from backend.agents.settings import AgentSettings
from backend.agents.semantics import GOAL_INSTRUCTIONS, STRUCTURED_GOAL_INSTRUCTIONS
from benchmarks.model_observer import ModelObserver


def test_real_sdk_sends_strict_contract_and_unwraps_valid_decision():
    def respond(request):
        payload = json.loads(request.content)
        spec = payload['response_format']['json_schema']
        assert payload['response_format']['type'] == 'json_schema' and spec['strict'] is True
        assert 'decision' in spec['schema']['properties']
        user_payload = json.loads(payload['messages'][-1]['content'])
        assert user_payload['decision_schema']['properties'] == spec['schema']['properties']
        # Some endpoints constrain decoding without exposing field names to model context.
        value = {'decision': {'status':'custom', 'goal':Goal(description='Count corners', event_types=['corner']).model_dump(mode='json')}}
        return httpx.Response(200, json={'id':'synthetic','object':'chat.completion','created':1,'model':'test',
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(value)}}]})
    observer = ModelObserver(transport_factory=lambda:httpx.MockTransport(respond))
    agent = GoalAgent(LocalJsonModel('http://local.invalid/v1','test',transport=observer), response_mode='schema')
    result = asyncio.run(agent.define('Count corners', {}))
    assert result.status == 'custom' and result.goal.event_types == ('corner',)
    assert observer.calls[0]['strict_requested'] is True
    assert len(observer.calls[0]['wire_schema_sha256']) == 64


def test_provider_rejection_never_silently_downgrades_to_prompt_mode():
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(400, json={'error':{'message':'Structured output unavailable','type':'invalid_request_error'}})
    model = LocalJsonModel('http://local.invalid/v1','test',transport=httpx.MockTransport(respond))
    with pytest.raises(ModelError) as exc:
        asyncio.run(GoalAgent(model, response_mode='schema').define('Count corners', {}))
    assert exc.value.reason == 'http_400' and not exc.value.retryable
    assert len(calls) == 1 and calls[0]['response_format']['json_schema']['strict']


def test_schema_ignoring_provider_is_rejected_locally():
    class IgnoresSchema:
        async def complete(self, system, payload, *, response_schema):
            return {'decision': {'status':'custom', 'goal':{'description':'Count corners'}}}
    with pytest.raises(ValueError):
        asyncio.run(GoalAgent(IgnoresSchema(), response_mode='schema').define('Count corners', {}))


def test_output_mode_is_explicit_and_validated(monkeypatch):
    monkeypatch.setenv('AGENT_GOAL_OUTPUT_MODE','schema')
    assert AgentSettings.from_env().goal_output_mode == 'schema'
    monkeypatch.setenv('AGENT_GOAL_OUTPUT_MODE','silently-fallback')
    with pytest.raises(ValueError, match='AGENT_GOAL_OUTPUT_MODE'):
        AgentSettings.from_env()


@pytest.mark.parametrize(('field', 'value'), [('period', '2'), ('after_seconds', '3600'),
                                             ('event_types', 'corner')])
def test_schema_ignoring_provider_cannot_coerce_wrong_json_types(field, value):
    class IgnoresTypes:
        async def complete(self, system, payload, *, response_schema):
            goal = Goal(description='Count corners', event_types=['corner']).model_dump(mode='json')
            goal[field] = value
            return {'decision': {'status': 'custom', 'goal': goal}}
    with pytest.raises(ValueError):
        asyncio.run(GoalAgent(IgnoresTypes(), response_mode='schema').define('Count corners', {}))


def test_time_unit_policy_is_present_in_both_transports():
    # This requirement was accidentally lost while compacting the old prompt.
    assert 'Bare match-time numbers mean MINUTES' in GOAL_INSTRUCTIONS
    assert 'Bare match-time numbers mean MINUTES' in STRUCTURED_GOAL_INSTRUCTIONS
