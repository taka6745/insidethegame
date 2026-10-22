"""Independent action ledger for shared deterministic metric arithmetic."""
import hashlib
import json
import pytest
from pydantic import ValidationError
from backend.agents.models import Goal
from backend.models.actions import SpadlAction
from backend.models.rules import Rule, Predicate
from backend.services.filter_engine import FilterEngine


def leaf(results=(), *, team='chelsea', operation='count', start=3600):
    terms = [Predicate(field='action_type', op='eq', value='pass'),
             Predicate(field='team_id', op='eq', value=team),
             Predicate(field='match_time_seconds', op='gte', value=start)]
    if results:
        terms.append(Predicate(field='result', op='in', value=results))
    return Rule(match_id='match', operation=operation, predicates=terms,
                sum_field='distance_metres' if operation in {'sum', 'count_present'} else None)


def formula(operation='percentage', *, left=None, right=None):
    return Rule(match_id='match', operation=operation,
                inputs=(left or leaf(('success',)), right or leaf(('success', 'fail'))))


def event(identifier, time, result='success', distance=0.0, **changes):
    """A pass along x: its ball distance is `distance` metres."""
    return SpadlAction(**(dict(match_id='match', action_id=identifier, action_type='pass', team_id='chelsea',
                               match_time_seconds=time, period=2, result=result, bodypart='foot', start_x=0.0,
                               start_y=34.0, end_x=distance, end_y=34.0, start_zone='own_box', end_zone='own_box',
                               seq=1, final_seq=1) | changes))


LEDGER = [event(1,3599,'success',10), event(2,3600,'success',20),
          event(3,3601,'fail',30), event(4,3602,'success'),
          event(5,3603,'offside',40), event(6,3604,'success',50,team_id='united'),
          event(7,3605,'success',action_type='shot')]


def test_incremental_gold_ledger_and_zero_distances():
    engine = FilterEngine()
    definitions = [formula(), formula('average',left=leaf(operation='sum'),right=leaf(operation='count_present')),
                   formula('difference',left=leaf(('success','fail')),right=leaf(('success','fail'),team='united'))]
    ids = [engine.register(rule).calculation_id for rule in definitions]
    assert engine.get(ids[0]).value is None
    for row in LEDGER:
        engine.ingest(row)
    assert [engine.get(i).value for i in ids] == pytest.approx([200/3,22.5,2])
    engine.ingest(event(8,3606,'fail',0))
    assert [engine.get(i).value for i in ids] == pytest.approx([50,18,3])
    versions = [engine.get(i).version for i in ids]
    assert engine.ingest(event(8,3606,'fail',0)) == []  # A redelivered final action changes nothing.
    assert [engine.get(i).version for i in ids] == versions
    assert engine.ingest(event(9,3605,'success',match_id='other')) == []
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
    update = event(20,3610,'success',30)
    assert restored.ingest(update) == engine.ingest(update)


def test_shared_input_update_visits_only_dependent_formulas():
    engine = FilterEngine()
    for index in range(1000):
        engine.register(formula(left=leaf(('success',),team=f'team-{index}'),
                                right=leaf(('success','fail'),team=f'team-{index}')))
    active = engine.register(formula())
    engine.register(formula('ratio'))  # Same two counters, distinct presentation operation.
    assert engine.leaf_count == 2002
    changed = engine.ingest(event(1,3600,'success'))
    assert engine.last_candidate_count == 2
    assert engine.last_formula_evaluation_count == 2
    assert engine.get(active.calculation_id).value == 100
    assert len(changed) == 2


def test_spadl_identity_and_unit_validation():
    old = Rule(match_id='match',predicates=[Predicate(field='action_type',op='eq',value='pass')])
    terms = ['{"field":"action_type","op":"eq","value":"pass"}']
    expected = hashlib.sha256(json.dumps(['spadl-v1','match','count',None,terms],separators=(',',':')).encode()).hexdigest()
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


def test_average_goal_includes_zero_distances():
    goal = Goal(description='Mean completed pass distance',operation='average',sum_field='distance_metres',
                action_types=['pass'],results=['success'],team_ids=['chelsea'],from_seconds=3600)
    engine = FilterEngine()
    result = engine.register(goal.target_rule('match'),LEDGER)
    assert result.value == 10
    engine.ingest(event(30,3608,'success',0))
    assert engine.get(result.calculation_id).value == pytest.approx(20/3)
