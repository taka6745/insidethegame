"""Independent oracle validity after fictional catalogue remapping; no model calls."""
from collections import Counter
from copy import deepcopy
import json

from backend.adapters.events import OptaInspiredAdapter
from benchmarks.cases import cases
from benchmarks.correctness import FIXTURE, gold_check, evaluate_rule
from benchmarks.data_transfer_cases import STAT_REQUESTS, data_transfer_cases, remap_fixture
from backend.models.rules import Rule


def test_frozen_cohort_scope_and_incomplete_requests():
    selected = data_transfer_cases()
    assert len(selected) == len({row['id'] for row in selected}) == 20
    assert Counter(row['quality'] for row in selected) == {
        'clear':6, 'average':6, 'ambiguous':4, 'control':4}
    assert sum(row['must_clarify'] for row in selected) == 4
    for row in selected:
        assert len(row['replies']) == 1
        if row['quality'] == 'control':
            assert row['expected_status'] == ['unsupported']
        else:
            assert 'expected_rule' in row


def test_entity_remap_preserves_independent_revision_weights_and_source():
    source = json.loads(FIXTURE.read_text())
    original = deepcopy(source)
    scenario = remap_fixture(source)
    assert source == original
    assert scenario['players'][0] == {'id':'noah-laurent','name':'Noah Laurent','team_id':'ridge'}
    assert scenario['events'][0]['playerId'] == 'noah-laurent'
    assert scenario['events'][0]['teamId'] == 'ridge'
    for before, after in zip(source['events'], scenario['events']):
        for key in ('eventId','revision','sequence','timeMin','timeSec','periodId','qualifiers','deleted'):
            assert before[key] == after[key]
    selected = data_transfer_cases()
    gold = cases()
    for row, (number, _, _, _) in zip(selected, STAT_REQUESTS):
        assert row['expected_weights'] == gold[number - 1]['expected_weights']
        assert row['expected_rule'] == remap_fixture(gold[number - 1]['expected_rule'])
    events = [OptaInspiredAdapter().adapt(raw) for raw in scenario['events']]
    checks = gold_check(scenario, events, selected)
    assert len(checks) == 16
    assert all(row['ok'] for row in checks)
    assert all(row['deliveries_checked'] == len(scenario['events']) for row in checks)


def test_oracle_rejects_wrong_actor_category_and_redundant_scope():
    scenario = remap_fixture(json.loads(FIXTURE.read_text()))
    events = [OptaInspiredAdapter().adapt(raw) for raw in scenario['events']]
    case = data_transfer_cases()[2]  # Shooter's saved shots in the second half.
    wrong = deepcopy(case['expected_rule'])
    wrong['predicates'] = [p for p in wrong['predicates'] if p['field'] != 'outcome']
    for predicate in wrong['predicates']:
        if predicate['field'] == 'event_type':
            predicate['op'], predicate['value'] = 'eq', 'save'
    assert evaluate_rule(case, Rule.model_validate(wrong), events, scenario['events'])['reason'] == 'wrong_event_value'
    redundant = deepcopy(case['expected_rule'])
    redundant['predicates'].append({'field':'team_id','op':'in','value':['ridge']})
    # A fixture-equivalent restriction still fails semantic constraint equality.
    assert evaluate_rule(case, Rule.model_validate(redundant), events, scenario['events'])['reason'] == 'different_constraints'
