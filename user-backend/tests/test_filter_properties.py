"""Differential checks against a scalar interpreter with no production matching code.

These synthetic cases cover the DSL rather than the saved match or agent prompts.
Seeded generation keeps failures reproducible without a property-test dependency.
"""
import operator
import random
from fractions import Fraction

import pytest

from backend.models.actions import SpadlAction
from backend.models.rules import Predicate, Rule
from backend.services.filter_engine import FilterEngine
from backend.services.time_index import TimeIndex

COMPARISONS = {"eq": operator.eq, "gt": operator.gt, "gte": operator.ge,
               "lt": operator.lt, "lte": operator.le, "in": lambda actual, values: actual in values}
CATEGORIES = {
    "action_type": ["pass", "corner_crossed", "shot", "dribble", "tackle", "clearance"],
    "team_id": ["team-a", "team-b"],
    "player_id": ["player-a", "player-b", "player-c"],
    "bodypart": ["head", "foot", "other"],
    "result": ["success", "fail", "offside"],
    "end_zone": ["opp_box", "final_third", "own_box"],
}
REQUIRED = {"action_type", "team_id", "bodypart", "result", "end_zone"}
CLOCKS = [0, 1, 59, 60, 61, 2700, 3600, 5400, 12000]


def test_segment_decomposition_matches_scalar_predicates_across_entire_clock_domain():
    rng = random.Random(31337)
    index, definitions = TimeIndex(), {}
    for number in range(80):
        terms = []
        for _ in range(rng.randrange(5)):
            op = rng.choice(list(COMPARISONS))
            value = ([rng.randrange(48001) / 4 for _ in range(5)] if op == "in"
                     else rng.randrange(48001) / 4)
            terms.append({"field": "match_time_seconds", "op": op, "value": value})
        identifier = str(number)
        definitions[identifier] = terms
        index.add(identifier, tuple(Predicate.model_validate(p) for p in terms))
    for second in range(12001):
        expected = {identifier for identifier, terms in definitions.items()
                    if all(COMPARISONS[p["op"]](second, p["value"]) for p in terms)}
        actual = index.matching(second)
        assert set(actual) == expected
        assert len(actual) == len(expected)
        assert index.last_probe_count <= 15


def scalar_total(rule, latest):
    """Read plain contract data, not Rule.matches/contribution or either index."""
    total = Fraction(0)
    for action in latest.values():
        if action["match_id"] != rule["match_id"]:
            continue
        if not all(action[p["field"]] is not None and
                   COMPARISONS[p["op"]](action[p["field"]], p["value"])
                   for p in rule["predicates"]):
            continue
        # Every generated action runs along x from 0, so its ball distance is end_x.
        total += Fraction(1) if rule["operation"] == "count" else Fraction(str(action["end_x"]))
    return total


def definitions(rng):
    # Explicit coverage for wildcard count/sum, unindexable numeric ranges,
    # conflicting predicates, and membership expansion above the 64-key budget.
    terms = [[], [], [{"field": "period", "op": "gt", "value": 1}],
             [{"field": "team_id", "op": "eq", "value": "team-a"},
              {"field": "team_id", "op": "eq", "value": "team-b"}],
             [{"field": "team_id", "op": "in", "value": ["team-a", "team-b"] + [f"t{i}" for i in range(30)]},
              {"field": "player_id", "op": "in", "value": ["player-a", "player-b"] + [f"p{i}" for i in range(30)]}]]
    for _ in range(65):
        predicates = []
        for _ in range(rng.randrange(1, 9)):
            field = rng.choice([*CATEGORIES, "period", "match_time_seconds"])
            if field in CATEGORIES:
                values = CATEGORIES[field]
                op = rng.choice(["eq", "in"])
            else:
                values = [1, 2, 3] if field == "period" else CLOCKS + [59.5, 60.5, 3600.5]
                op = rng.choice(list(COMPARISONS))
            value = rng.sample(values, rng.randrange(1, min(4, len(values)) + 1)) if op == "in" else rng.choice(values)
            predicates.append({"field": field, "op": op, "value": value})
        terms.append(predicates)
    result = []
    for number, predicates in enumerate(terms):
        operation = "sum" if number % 2 else "count"
        result.append(Rule(match_id="match-a" if number % 3 else "match-b", predicates=predicates,
                           operation=operation, sum_field="distance_metres" if operation == "sum" else None))
    return result


def generated_action(rng, latest, step):
    key = rng.choice(["match-a", "match-b"]), rng.randrange(20)
    previous = latest.get(key)
    if previous and step % 7 == 0:
        return SpadlAction.model_validate(previous)  # Exact duplicate delivery.
    if previous:
        key = key[0], 20 + step  # A final action never changes: a new one gets a new id.
    values = {field: rng.choice(options + ([None] if field not in REQUIRED else []))
              for field, options in CATEGORIES.items()}
    return SpadlAction(match_id=key[0], action_id=key[1], period=rng.choice([1, 2, 3]),
                       match_time_seconds=rng.choice(CLOCKS), start_x=0.0, start_y=34.0,
                       end_x=rng.choice([0.0, 0.1, 0.2, 12.5, 105.0]), end_y=34.0, start_zone="own_box",
                       seq=1, final_seq=1, **values)


@pytest.mark.parametrize("seed", [11, 29, 97])
def test_general_dsl_prefixes_late_registration_and_duplicates_match_independent_oracle(seed):
    rng = random.Random(seed)
    engine, latest = FilterEngine(), {}
    active, totals, versions = {}, {}, {}
    rules = definitions(rng)

    def register(batch):
        for rule in batch:
            result = engine.register(rule)
            if result.calculation_id in active:
                continue
            active[result.calculation_id] = rule.model_dump(mode="json")
            totals[result.calculation_id] = scalar_total(active[result.calculation_id], latest)
            versions[result.calculation_id] = 1
            assert result.value == float(totals[result.calculation_id])

    register(rules[:35])
    for step in range(150):
        if step == 60:
            register(rules[35:])
        action = generated_action(rng, latest, step)
        previous = latest.get((action.match_id, action.action_id))
        if previous and step % 13 == 0:
            conflict = SpadlAction.model_validate({**previous, "end_x": 1.5 if previous["end_x"] != 1.5 else 2.5})
            snapshot = engine.calculations
            with pytest.raises(ValueError, match="Conflicting"):
                engine.ingest(conflict)
            assert engine.calculations == snapshot
        results = engine.ingest(action)
        assert [r.calculation_id for r in results] == sorted(r.calculation_id for r in results)
        assert len(results) == len({r.calculation_id for r in results})
        latest[action.match_id, action.action_id] = action.model_dump()
        changed = set()
        for identifier, rule in active.items():
            expected = scalar_total(rule, latest)
            if expected != totals[identifier]:
                changed.add(identifier)
                versions[identifier] += 1
            totals[identifier] = expected
            actual = engine.get(identifier)
            assert (actual.value, actual.version) == (float(expected), versions[identifier])
        assert {r.calculation_id for r in results} == changed

    # Late registration over the same actions, in any arrival order, agrees.
    history = [SpadlAction.model_validate(row) for row in latest.values()]
    rng.shuffle(history)
    rebuilt = FilterEngine()
    for action in history:
        rebuilt.ingest(action)
    for rule in rules:
        result = rebuilt.register(rule)
        assert result.value == float(scalar_total(rule.model_dump(mode="json"), latest))
        assert result.value == engine.get(result.calculation_id).value
        assert rebuilt.register(rule).calculation_id == result.calculation_id
