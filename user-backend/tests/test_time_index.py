"""Clock boundaries and shared work must not depend on the number of windows."""
import random
from decimal import Decimal

from backend.models.actions import SpadlAction
from backend.models.rules import Predicate, Rule
from backend.services.filter_engine import FilterEngine
from backend.services.time_index import TimeIndex


def term(op, value, field="match_time_seconds"):
    return Predicate(field=field, op=op, value=value)


def event(identifier=0, **values):
    base = {"match_id": "match", "action_id": identifier, "action_type": "pass", "result": "success",
            "bodypart": "foot", "team_id": "team", "match_time_seconds": 60, "period": 1, "start_x": 0.0, "start_y": 34.0,
            "end_x": 0.0, "end_y": 34.0, "start_zone": "own_box", "end_zone": "own_box", "seq": 1, "final_seq": 1}
    return SpadlAction(**(base | values))


def test_time_index_fractional_integer_endpoints_and_conjunctions():
    definitions = [
        (term("gt", 59.5), term("lt", 60.5)),
        (term("gte", 60.5), term("lte", 61.5)),
        (term("eq", 60.5),),
        (term("in", [59, 60, 61, 60.5]), term("in", [60, 61]), term("lt", 61)),
        (term("gte", 61), term("lte", 59)),
        (term("gt", 12000),),
        (term("lt", 0),),
        (),
    ]
    index = TimeIndex()
    for number, terms in enumerate(definitions):
        index.add(str(number), terms)
    for second in [0, 59, 60, 61, 62, 12000]:
        item = event(match_time_seconds=second)
        expected = {str(n) for n, terms in enumerate(definitions) if all(t.matches(item) for t in terms)}
        actual = index.matching(second)
        assert set(actual) == expected
        assert len(actual) == len(set(actual)), "A rule must not be returned twice"
        assert index.last_probe_count <= 15


def test_many_future_windows_are_excluded_without_predicate_scans():
    engine = FilterEngine()
    for second in range(1000):
        engine.register(Rule(match_id="match", predicates=(term("eq", second),)))
    changed = engine.ingest(event())
    assert len(changed) == 1
    assert engine.last_candidate_count == 1
    assert engine.last_family_evaluation_count == 1
    assert engine.last_time_probe_count == 15


def test_overlapping_windows_share_predicates_but_emit_every_changed_result():
    engine = FilterEngine()
    for second in range(1000):
        engine.register(Rule(match_id="match", predicates=(term("gte", 0), term("lte", second + 100))))
    changed = engine.ingest(event())
    assert len(changed) == 1000
    assert engine.last_candidate_count == 1000
    assert engine.last_family_evaluation_count == 1
    assert all(result.value == 1 and result.version == 2 for result in changed)
    # A redelivered final action changes nothing and evaluates no family.
    assert engine.ingest(event()) == []
    assert engine.last_candidate_count == 0


def test_random_window_prefixes_and_late_registration_match_scalar_oracle():
    rng = random.Random(93017)
    engine = FilterEngine()
    rules = []
    for number in range(80):
        terms = [term(rng.choice(["gt", "gte", "lt", "lte"]), rng.choice([0, 59.5, 60, 60.5, 61, 12000]))]
        if number % 3 == 0:
            terms.append(term("in", [0, 59, 60, 61, 12000]))
        if number % 4 == 0:
            terms.append(term("gte", 2, "period"))
        if number % 5 == 0:
            terms.append(term("in", ["a", "b"], "player_id"))
        operation = "count" if number % 2 else "sum"
        rule = Rule(match_id="match", predicates=tuple(terms), operation=operation,
                    sum_field="distance_metres" if operation == "sum" else None)
        if rule.calculation_id not in {r.calculation_id for r in rules}:
            rules.append(rule)
            engine.register(rule)
    seen = []
    versions = {r.calculation_id: 1 for r in rules}
    totals = {r.calculation_id: Decimal(0) for r in rules}
    for step in range(100):
        item = event(step, match_time_seconds=rng.choice([0, 59, 60, 61, 12000]), period=rng.choice([1, 2]),
                     player_id=rng.choice([None, "a", "b", "c"]), end_x=rng.choice([0.0, 0.1, 0.2, 10.5]))
        seen.append(item)
        changes = {r.calculation_id: r for r in engine.ingest(item)}
        for rule in rules:
            expected = sum((Decimal(str(rule.contribution(e))) for e in seen), Decimal(0))
            identifier = rule.calculation_id
            if expected != totals[identifier]:
                versions[identifier] += 1
                assert identifier in changes
            else:
                assert identifier not in changes
            totals[identifier] = expected
            result = engine.get(identifier)
            assert result.value == float(expected)
            assert result.version == versions[identifier]
        assert engine.ingest(item) == []
    for rule in rules:
        assert FilterEngine().register(rule, seen).value == engine.get(rule.calculation_id).value
