"""Differential checks against a scalar interpreter with no production matching code.

These synthetic cases cover the DSL rather than the saved match or agent prompts.
Seeded generation keeps failures reproducible without a property-test dependency.
"""
import operator
import random
from fractions import Fraction

import pytest

from backend.models.events import Event
from backend.models.rules import Predicate, Rule
from backend.services.filter_engine import FilterEngine
from backend.services.time_index import TimeIndex

COMPARISONS = {"eq": operator.eq, "gt": operator.gt, "gte": operator.ge,
               "lt": operator.lt, "lte": operator.le, "in": lambda actual, values: actual in values}
CATEGORIES = {
    "event_type": ["pass", "corner", "shot", "goal", "touch", "card"],
    "team_id": ["team-a", "team-b"],
    "player_id": ["player-a", "player-b", "player-c"],
    "body_part": ["head", "foot", "other"],
    "outcome": ["success", "failure", "red"],
}
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
    for event in latest.values():
        if event["deleted"] or event["match_id"] != rule["match_id"]:
            continue
        if not all(event[p["field"]] is not None and
                   COMPARISONS[p["op"]](event[p["field"]], p["value"])
                   for p in rule["predicates"]):
            continue
        value = 1 if rule["operation"] == "count" else event[rule["sum_field"]] or 0
        total += Fraction(str(value))
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


def generated_event(rng, latest, history, step):
    key = rng.choice(["match-a", "match-b"]), str(rng.randrange(20))
    previous = latest.get(key)
    if previous and step % 7 == 0:
        return Event.model_validate(previous)  # Exact duplicate.
    if previous and previous["revision"] > 1 and step % 11 == 0:
        older = [e for e in history if (e.match_id, e.event_id) == key and e.revision < previous["revision"]]
        return rng.choice(older) if older else Event.model_validate(previous)
    # Repeated IDs deliberately change categories, clock, measurement and tombstone.
    values = {field: rng.choice(options + ([None] if field != "event_type" else []))
              for field, options in CATEGORIES.items()}
    return Event(event_id=key[1], match_id=key[0], revision=previous["revision"] + 1 if previous else 2,
                 period=rng.choice([1, 2, 3]), match_time_seconds=rng.choice(CLOCKS),
                 distance_metres=rng.choice([None, 0.0, 0.1, 0.2, 12.5, 200.0]),
                 deleted=step % 9 == 0, **values)


@pytest.mark.parametrize("seed", [11, 29, 97])
def test_general_dsl_prefixes_late_registration_and_revisions_match_independent_oracle(seed):
    rng = random.Random(seed)
    engine, latest, history = FilterEngine(), {}, []
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
        event = generated_event(rng, latest, history, step)
        previous = latest.get((event.match_id, event.event_id))
        if previous and step % 13 == 0:
            conflict = Event.model_validate({**previous, "deleted": not previous["deleted"]})
            snapshot = engine.calculations
            with pytest.raises(ValueError, match="Conflicting"):
                engine.ingest(conflict)
            assert engine.calculations == snapshot
        results = engine.ingest(event)
        assert [r.calculation_id for r in results] == sorted(r.calculation_id for r in results)
        assert len(results) == len({r.calculation_id for r in results})
        history.append(event)
        if previous is None or event.revision > previous["revision"]:
            latest[event.match_id, event.event_id] = event.model_dump()
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

    # Registration imports history before computing its initial value; the same
    # latest-revision set must agree regardless of arrival order and late creation.
    rng.shuffle(history)
    rebuilt = FilterEngine()
    for event in history:
        rebuilt.ingest(event)
    for rule in rules:
        result = rebuilt.register(rule)
        assert result.value == float(scalar_total(rule.model_dump(mode="json"), latest))
        assert result.value == engine.get(result.calculation_id).value
        assert rebuilt.register(rule).calculation_id == result.calculation_id
