"""Model-facing contracts remain validated, and repair diagnostics stay safe."""
import asyncio
import json

from backend.agents.contracts import decision_contract
from backend.agents.models import GoalDecision
from backend.agents.orchestrator import GoalAgent
from backend.agents.compiler import StructuredRuleCompiler
from backend.agents.workflow import RuleWorkflow


class Scripted:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    async def complete(self, instructions, payload):
        self.calls.append((instructions, payload))
        return next(self.replies)


def test_inline_contract_keeps_enums_bounds_and_required_fields():
    schema = decision_contract()
    encoded = json.dumps(schema)
    assert '$ref' not in encoded and '$defs' not in encoded
    assert schema['required'] == ['status']
    assert schema['additionalProperties'] is False
    goal = schema['properties']['goal']['anyOf'][0]
    assert goal['required'] == ['description']
    assert goal['properties']['after_seconds']['anyOf'][0]['maximum'] == 12000
    assert 'header' not in goal['properties']['event_types']['items']['enum']
    assert 'shot' in goal['properties']['event_types']['items']['enum']
    assert len(encoded) < len(json.dumps(GoalDecision.model_json_schema()))


def test_baseline_schema_and_instructions_remain_selectable():
    model = Scripted([{'status': 'unsupported', 'message': 'No video data'}])
    agent = GoalAgent(model, instructions='baseline instructions', compact_contract=False)
    asyncio.run(agent.define('How tired is the player?', {}))
    instructions, payload = model.calls[0]
    assert instructions == 'baseline instructions'
    assert payload['decision_schema'] == GoalDecision.model_json_schema()


def test_schema_repairs_preserve_safe_diagnostics_and_never_publish_invalid_goal():
    model = Scripted([
        {'status': 'custom', 'goal': {'description': 'invalid', 'event_types': ['private-invalid-value']}},
        {'status': 'custom', 'goal': {'description': 'All corners', 'event_types': ['corner']}},
    ])
    result = asyncio.run(RuleWorkflow(GoalAgent(model), StructuredRuleCompiler()).plan(
        'Count corners', {'match_id': 'match', 'players': [], 'teams': []}))
    assert result.status == 'ready'
    assert result.model_calls == 2 and result.goal_failure_reasons == ['goal_schema']
    assert 'private-invalid-value' not in json.dumps(model.calls[1])
    assert result.rule.predicates[0].value == ('corner',)


def test_timeout_diagnostics_remain_unknown_instead_of_claiming_no_failures():
    class RetryTimesOut:
        calls = 0

        async def complete(self, instructions, payload):
            self.calls += 1
            if self.calls == 1:
                return {"status": "custom", "goal": {"description": "Bad", "event_types": ["bad"]}}
            await asyncio.sleep(1)

    model = RetryTimesOut()
    result = asyncio.run(RuleWorkflow(GoalAgent(model), StructuredRuleCompiler(), timeout_seconds=0.05).plan(
        "Count corners", {"match_id": "match", "players": [], "teams": []}))
    assert result.status == "failed" and "timed out" in result.message
    assert model.calls == 2
    assert result.goal_failure_reasons is None
