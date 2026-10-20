"""Typed wire schema mechanics; no model or network calls."""
from copy import deepcopy

import pytest
from pydantic import BaseModel, Field, ValidationError

from backend.agents.contracts import decision_envelope_model, strict_decision_contract
from backend.agents.models import Goal, GoalDecision, Clarification


def branch(schema, name):
    return schema['$defs'][name]


def test_strict_contract_has_root_object_and_four_required_branches():
    schema = strict_decision_contract()
    assert schema['type'] == 'object'
    assert schema['required'] == ['decision'] and schema['additionalProperties'] is False
    choices = schema['properties']['decision']['anyOf']
    assert len(choices) == 4
    for choice in choices:
        definition = branch(schema, choice['$ref'].split('/')[-1])
        assert set(definition['required']) == set(definition['properties'])
        assert definition['additionalProperties'] is False
    assert branch(schema, 'CustomDecision')['required'] == ['status', 'goal']
    assert branch(schema, '_ReuseDecision')['properties']['standard_stat_id']['minLength'] == 1
    assert branch(schema, '_UnsupportedDecision')['properties']['message']['minLength'] == 1


def test_defaulted_fields_keep_original_types_and_constraints():
    schema = strict_decision_contract()
    goal = branch(schema, 'GoalWire')
    assert set(goal['required']) == set(goal['properties'])
    assert goal['properties']['event_types']['type'] == 'array'
    assert 'anyOf' not in goal['properties']['event_types']
    assert goal['properties']['operation']['enum'] == ['count', 'sum', 'average', 'percentage', 'ratio', 'difference']
    assert {'type':'null'} in goal['properties']['after_seconds']['anyOf']
    assert goal['properties']['after_seconds']['anyOf'][0]['maximum'] == 12000
    assert branch(schema, 'ClarificationWire')['properties']['options']['maxItems'] == 5
    assert branch(schema, 'ClarificationWire')['properties']['options']['items']['maxLength'] == 200
    def walk(value):
        if isinstance(value, dict):
            assert 'default' not in value
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
    walk(schema)


@pytest.mark.parametrize('decision', [
    {'status':'custom','goal':Goal(description='Count corners', event_types=['corner']).model_dump(mode='json')},
    {'status':'clarification','clarification':Clarification(question='Which player?').model_dump(mode='json')},
    {'status':'reuse','standard_stat_id':'goals'},
    {'status':'unsupported','message':'No video data'},
])
def test_wire_decisions_validate_and_round_trip_to_current_contract(decision):
    wire = decision_envelope_model().model_validate({'decision':decision})
    data = wire.model_dump(exclude_unset=True)['decision']
    assert GoalDecision.model_validate(data).status == decision['status']


@pytest.mark.parametrize('payload', [
    {}, {'decision':{'status':'custom'}}, {'decision':{'status':'clarification'}},
    {'decision':{'status':'reuse','standard_stat_id':''}},
    {'decision':{'status':'unsupported','message':''}},
    {'decision':{'status':'unsupported','message':'No','goal':{'description':'x'}}},
    {'decision':{'status':'custom','goal':{'description':'x','event_types':None}}},
    {'decision':{'status':'custom','goal':{'description':'x','unknown':True}}},
    {'decision':{'status':'custom','goal':{'description':'x','operation':'sum'}}},
    {'decision':{'status':'custom','goal':{'description':'x','after_seconds':75,'before_seconds':60}}},
    {'decision':{'status':'unsupported','message':'No'},'extra':True},
])
def test_wire_rejects_missing_extraneous_or_invalid_branch_payloads(payload):
    with pytest.raises(ValidationError):
        decision_envelope_model().model_validate(payload)


def test_goal_schema_evolves_without_mutating_original_models():
    snapshots = [deepcopy(model.model_json_schema()) for model in (Goal, GoalDecision, Clarification)]
    class FutureGoal(Goal):
        confidence_note: str = Field(default='', max_length=40)
    schema = strict_decision_contract(FutureGoal)
    props = branch(schema, 'FutureGoalWire')['properties']
    assert props['confidence_note']['type'] == 'string'
    assert props['confidence_note']['maxLength'] == 40
    assert 'confidence_note' in branch(schema, 'FutureGoalWire')['required']
    assert 'anyOf' not in props['confidence_note']
    assert 'confidence_note' not in branch(strict_decision_contract(), 'GoalWire')['properties']
    assert [model.model_json_schema() for model in (Goal, GoalDecision, Clarification)] == snapshots
    assert Goal(description='Default still works').event_types == ()


@pytest.mark.parametrize('container', ['direct', 'optional', 'array'])
def test_nested_schema_changes_require_explicit_wire_support(container):
    class Detail(BaseModel):
        label: str = ''
    annotation = {'direct': Detail, 'optional': Detail | None, 'array': tuple[Detail, ...]}[container]
    from pydantic import create_model
    future = create_model('FutureGoal', __base__=Goal, detail=(annotation, ...))
    with pytest.raises(ValueError, match='explicit strict wire adapter'):
        strict_decision_contract(future)


@pytest.mark.parametrize('field', list(Goal.model_fields))
def test_wire_rejects_each_missing_goal_field_even_when_source_has_default(field):
    payload = Goal(description='Count corners', event_types=['corner']).model_dump(mode='json')
    del payload[field]
    with pytest.raises(ValidationError):
        decision_envelope_model().model_validate({'decision':{'status':'custom','goal':payload}})


@pytest.mark.parametrize('field', list(Clarification.model_fields))
def test_wire_rejects_each_missing_clarification_field(field):
    payload = Clarification(question='Which player?').model_dump(mode='json')
    del payload[field]
    with pytest.raises(ValidationError):
        decision_envelope_model().model_validate({'decision':{'status':'clarification','clarification':payload}})


def test_required_subclasses_preserve_cross_field_and_numeric_validators():
    payload = Goal(description='Count corners').model_dump(mode='json')
    envelope = decision_envelope_model()
    for changes in ({'after_seconds':75,'before_seconds':60}, {'period':8}, {'operation':'sum'},
                    {'description':''}, {'event_types':['unknown']}, {'team_ids':None}):
        with pytest.raises(ValidationError):
            envelope.model_validate({'decision':{'status':'custom','goal':{**payload, **changes}}})
    assert Goal(description='Unchanged').operation == 'count'
    assert Clarification(question='Unchanged?').options == []
