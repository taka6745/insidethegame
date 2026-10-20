"""Independent recorded-event ledger for shared deterministic metric arithmetic."""
import hashlib
import json
import pytest
from pydantic import ValidationError
from backend.agents.models import Goal
from backend.models.events import Event
from backend.models.rules import Rule, Predicate
from backend.services.filter_engine import FilterEngine


def leaf(outcomes=(), *, team='chelsea', operation='count', start=3600):
    terms = [Predicate(field='event_type', op='eq', value='pass'),
             Predicate(field='team_id', op='eq', value=team),
             Predicate(field='match_time_seconds', op='gte', value=start)]
    if outcomes:
        terms.append(Predicate(field='outcome', op='in', value=outcomes))
    return Rule(match_id='match', operation=operation, predicates=terms,
                sum_field='distance_metres' if operation in {'sum', 'count_present'} else None)


def formula(operation='percentage', *, left=None, right=None):
    return Rule(match_id='match', operation=operation,
                inputs=(left or leaf(('success',)), right or leaf(('success', 'failure'))))


def event(identifier, time, outcome=None, distance=None, **changes):
    return Event(**(dict(event_id=identifier, match_id='match', event_type='pass', team_id='chelsea',
                        match_time_seconds=time, period=2, outcome=outcome, distance_metres=distance) | changes))


LEDGER = [event('e1',3599,'success',10), event('e2',3600,'success',20),
          event('e3',3601,'failure',30), event('e4',3602,'success'),
          event('e5',3603,None,40), event('e6',3604,'success',50,team_id='united'),
          event('e7',3605,'success',event_type='shot')]


def test_incremental_gold_ledger_corrections_and_missing_values():
    engine = FilterEngine()
    definitions = [formula(), formula('average',left=leaf(operation='sum'),right=leaf(operation='count_present')),
                   formula('difference',left=leaf(('success','failure')),right=leaf(('success','failure'),team='united'))]
    ids = [engine.register(rule).calculation_id for rule in definitions]
    assert engine.get(ids[0]).value is None
    for row in LEDGER:
        engine.ingest(row)
    assert [engine.get(i).value for i in ids] == pytest.approx([200/3,30,2])
    engine.ingest(event('e8',3606,'failure',0))
    assert [engine.get(i).value for i in ids] == pytest.approx([50,22.5,3])
    corrected = event('e3',3601,'success',60,revision=2)
    changes = engine.ingest(corrected)
    assert [engine.get(i).value for i in ids] == pytest.approx([75,30,3])
    assert sum(row.calculation_id == ids[0] for row in changes) == 1
    assert engine.last_formula_evaluation_count == 2  # difference's resolved count did not change
    deleted = event('e2',3600,'success',20,revision=2,deleted=True)
    engine.ingest(deleted)
    assert [engine.get(i).value for i in ids] == pytest.approx([200/3,100/3,2])
    versions = [engine.get(i).version for i in ids]
    assert engine.ingest(corrected) == engine.ingest(deleted) == []
    assert [engine.get(i).version for i in ids] == versions
    assert engine.ingest(event('other',3605,'success',match_id='other')) == []
    assert len(engine.calculations) == 3  # hidden inputs are not cards


@pytest.mark.parametrize('explicit_first',[True,False])
def test_leaf_reuse_promotion_and_restore(explicit_first):
    engine = FilterEngine()
    single, combined = leaf(('success',)), formula()
    if explicit_first:
        engine.register(single)
    engine.register(combined, LEDGER)
    engine.register(single)
    assert engine.count == 2 and engine.leaf_count == 2
    assert engine.get(single.calculation_id).value == 2
    assert engine.register(combined).value == pytest.approx(200/3)
    restored = FilterEngine()
    for row in LEDGER:
        restored.ingest(row)
    for definition in engine.rules.values():
        result = restored.register(Rule.model_validate_json(definition.model_dump_json()))
        restored.restore_version(result.calculation_id,engine.get(result.calculation_id).version)
    update = event('e3',3601,'success',30,revision=2)
    assert restored.ingest(update) == engine.ingest(update)


def test_shared_input_update_visits_only_dependent_formulas():
    engine = FilterEngine()
    for index in range(1000):
        engine.register(formula(left=leaf(('success',),team=f'team-{index}'),
                                right=leaf(('success','failure'),team=f'team-{index}')))
    active = engine.register(formula())
    engine.register(formula('ratio'))  # Same two counters, distinct presentation operation.
    assert engine.leaf_count == 2002
    changed = engine.ingest(event('p',3600,'success'))
    assert engine.last_candidate_count == 2
    assert engine.last_formula_evaluation_count == 2
    assert engine.get(active.calculation_id).value == 100
    assert len(changed) == 2


def test_legacy_identity_and_unit_validation():
    old = Rule(match_id='match',predicates=[Predicate(field='event_type',op='eq',value='pass')])
    terms = ['{"field":"event_type","op":"eq","value":"pass"}']
    expected = hashlib.sha256(json.dumps(['match','count',None,terms],separators=(',',':')).encode()).hexdigest()
    assert old.calculation_id == 'calc_'+expected
    for op in ('ratio','percentage','difference'):
        with pytest.raises(ValidationError, match='compatible'):
            formula(op,left=leaf(operation='sum'))
    with pytest.raises(ValidationError,match='subset'):
        formula(left=leaf(team='united'))
    with pytest.raises(ValidationError,match='same match'):
        formula(left=leaf().model_copy(update={'match_id':'other'}))
    with pytest.raises(ValidationError):
        Rule(match_id='match',operation='ratio',inputs=[formula(),leaf()])


def test_average_goal_excludes_missing_but_includes_zero():
    goal = Goal(description='Mean completed pass distance',operation='average',sum_field='distance_metres',
                event_types=['pass'],outcome='success',team_ids=['chelsea'],from_seconds=3600)
    engine = FilterEngine()
    result = engine.register(goal.target_rule('match'),LEDGER)
    assert result.value == 20
    engine.ingest(event('zero',3608,'success',0))
    assert engine.get(result.calculation_id).value == 10
