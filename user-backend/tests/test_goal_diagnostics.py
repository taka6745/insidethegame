"""Only bounded structural diagnostics may leave rejected goal validation."""
import asyncio
import json

from backend.agents.compiler import StructuredRuleCompiler
from backend.agents.orchestrator import GoalAgent
from backend.agents.workflow import RuleWorkflow


class Scripted:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.contexts = []

    async def complete(self, system, payload):
        self.contexts.append(json.loads(json.dumps(payload)))
        return next(self.replies)


def plan(model, coder=None):
    return asyncio.run(RuleWorkflow(GoalAgent(model), coder or StructuredRuleCompiler()).plan(
        'Count corners', {'match_id':'match', 'players':[], 'teams':[]}))


def test_missing_and_extra_field_diagnostics_survive_success_without_values():
    model = Scripted([
        {'status':'custom','goal':{'private-key-secret':'private-value-secret'}},
        {'status':'custom','goal':{'description':'Corners','event_types':['corner']}},
    ])
    result = plan(model)
    assert result.status == 'ready'
    errors = result.goal_validation_errors
    assert {error['type'] for error in errors} == {'missing', 'extra_forbidden'}
    assert {error['attempt'] for error in errors} == {1}
    assert all(set(error) == {'attempt','path','type'} for error in errors)
    assert {'attempt':1,'path':'goal.description','type':'missing'} in errors
    assert {'attempt':1,'path':'goal.<extra>','type':'extra_forbidden'} in errors
    saved = json.dumps({'outcome':result.model_dump(mode='json'),'retry':model.contexts[1]})
    assert 'private-key-secret' not in saved and 'private-value-secret' not in saved


def test_both_failed_attempts_preserve_error_attempt_numbers():
    model = Scripted([{'status':'custom','goal':{}}, {'status':'custom','goal':{}}])
    result = plan(model)
    assert result.status == 'failed'
    assert [error['attempt'] for error in result.goal_validation_errors] == [1, 2]
    assert result.goal_failure_reasons == ['goal_schema', 'goal_schema']


def test_noncustom_result_preserves_prior_validation_errors():
    result = plan(Scripted([{'status':'custom','goal':{}}, {'status':'unsupported','message':'No data'}]))
    assert result.status == 'unsupported'
    assert result.goal_validation_errors == [{'attempt':1,'path':'goal.description','type':'missing'}]


def test_coding_failure_preserves_goal_validation_errors():
    class BrokenCompiler:
        async def generate(self, *args):
            raise ValueError('Broken')
    model = Scripted([{'status':'custom','goal':{}}, {'status':'custom','goal':{'description':'Corners'}}])
    result = plan(model, BrokenCompiler())
    assert result.status == 'failed'
    assert result.goal_validation_errors == [{'attempt':1,'path':'goal.description','type':'missing'}]


def test_timeout_reports_unknown_diagnostics_instead_of_empty():
    class Slow:
        calls = 0
        async def complete(self, *args):
            self.calls += 1
            if self.calls == 1:
                return {'status':'custom','goal':{}}
            await asyncio.sleep(1)
    result = asyncio.run(RuleWorkflow(GoalAgent(Slow()), StructuredRuleCompiler(), timeout_seconds=.02).plan(
        'Count corners', {'match_id':'match', 'players':[], 'teams':[]}))
    assert result.status == 'failed' and result.goal_validation_errors is None
