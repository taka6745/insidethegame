"""Reference values, revision semantics and bounded candidate-work tests."""
import json
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.adapters.events import OptaInspiredAdapter
from backend.models.events import Event
from backend.models.rules import Predicate, Rule
from backend.services.filter_engine import FilterEngine

SCENARIO = json.loads((Path(__file__).parents[1] / "fixtures/filter-lab.json").read_text())


def event(**changes):
    return Event(**({"event_id": "e1", "match_id": "match", "event_type": "corner", "team_id": "chelsea", "match_time_seconds": 4025, "period": 2} | changes))


def rule(*predicates, **changes):
    return Rule(match_id="match", predicates=predicates, **changes)


def predicate(field, value, op="eq"):
    return Predicate(field=field, op=op, value=value)


@pytest.mark.parametrize("preset", SCENARIO["presets"], ids=lambda p: p["id"])
def test_examples_from_natural_requests(preset):
    engine, adapter = FilterEngine(), OptaInspiredAdapter()
    definition = Rule.model_validate(preset["rule"])
    identifier = engine.register(definition).calculation_id
    for raw in SCENARIO["events"]:
        engine.ingest(adapter.adapt(raw))
    assert engine.get(identifier).value == preset["expected_final"]
    # Same stream as historical backfill yields the same count, including VAR.
    backfilled = FilterEngine().register(definition, [adapter.adapt(raw) for raw in SCENARIO["events"]])
    assert backfilled.value == preset["expected_final"]


def test_boundary_60_minutes_is_strict_and_teamless_rule_still_matches():
    engine = FilterEngine()
    strict = engine.register(rule(predicate("event_type", "corner"), predicate("match_time_seconds", 3600, "gt")))
    inclusive = engine.register(rule(predicate("event_type", "corner"), predicate("match_time_seconds", 3600, "gte")))
    engine.ingest(event(match_time_seconds=3600))
    assert engine.get(strict.calculation_id).value == 0
    assert engine.get(inclusive.calculation_id).value == 1
    engine.ingest(event(event_id="e2", match_time_seconds=3601, team_id="madrid"))
    assert engine.get(strict.calculation_id).value == 1
    assert engine.get(inclusive.calculation_id).value == 2


def test_100k_unique_filters_do_not_mean_100k_lookups():
    engine = FilterEngine()
    for index in range(100_000):
        engine.register(rule(predicate("event_type", "shot"), predicate("player_id", f"player-{index}")))
    broad = engine.register(rule(predicate("match_time_seconds", 3600, "gt")))
    corner = engine.register(rule(predicate("event_type", "corner")))
    changes = engine.ingest(event())
    assert {r.calculation_id for r in changes} == {broad.calculation_id, corner.calculation_id}
    assert engine.last_candidate_count == 2
    assert engine.last_index_probe_count == 64
    engine.ingest(event(event_id="shot", event_type="shot", player_id="player-4321"))
    assert engine.last_candidate_count == 2  # one player rule and the broad rule


def test_correction_visits_old_and_new_index_buckets():
    engine = FilterEngine()
    chelsea = engine.register(rule(predicate("team_id", "chelsea")))
    madrid = engine.register(rule(predicate("team_id", "madrid")))
    engine.ingest(event())
    changes = engine.ingest(event(revision=2, team_id="madrid"))
    assert {r.calculation_id: r.value for r in changes} == {chelsea.calculation_id: 0, madrid.calculation_id: 1}
    assert engine.last_candidate_count == 2
    assert engine.last_index_probe_count == 128


def test_retraction_before_original_prevents_resurrection_by_old_revision():
    engine = FilterEngine()
    calc = engine.register(rule())
    assert engine.ingest(event(revision=2, deleted=True)) == []
    assert engine.ingest(event()) == []
    assert engine.get(calc.calculation_id).value == 0
    assert engine.ingest(event(revision=3))[0].value == 1


def test_duplicate_and_conflicting_revision():
    engine = FilterEngine()
    calc = engine.register(rule())
    first = engine.ingest(event())[0]
    assert engine.ingest(event()) == []
    assert engine.last_candidate_count == 0
    with pytest.raises(ValueError, match="Conflicting"):
        engine.ingest(event(team_id="madrid"))
    assert engine.get(calc.calculation_id) == first


def test_equivalent_rules_reuse_id_despite_order_membership_and_duplicates():
    a = rule(predicate("team_id", "chelsea"), predicate("event_type", ["shot", "goal"], "in"))
    b = rule(predicate("event_type", ["goal", "shot", "goal"], "in"), predicate("team_id", ["chelsea"], "in"), predicate("team_id", "chelsea"))
    engine = FilterEngine()
    assert engine.register(a).calculation_id == engine.register(b).calculation_id
    assert engine.count == 1


def test_matches_are_namespaced_and_missing_optional_fields_are_not_matches():
    engine = FilterEngine()
    calc = engine.register(rule(predicate("player_id", "mbappe")))
    assert engine.ingest(event(match_id="other", player_id="mbappe")) == []
    assert engine.ingest(event(player_id=None)) == []
    assert engine.get(calc.calculation_id).value == 0


def test_membership_intersection_and_contradictory_rules():
    engine = FilterEngine()
    calc = engine.register(rule(predicate("event_type", ["corner", "shot"], "in"), predicate("event_type", "corner")))
    impossible = engine.register(rule(predicate("team_id", "chelsea"), predicate("team_id", "madrid")))
    engine.ingest(event())
    assert engine.get(calc.calculation_id).value == 1
    assert engine.get(impossible.calculation_id).value == 0
    assert engine.last_candidate_count == 1


def test_membership_compound_index_and_bounded_expansion():
    engine = FilterEngine()
    # 32 x 32 combinations would explode registration. The engine indexes only
    # a bounded subset and applies remaining predicates to candidate events.
    calc = engine.register(rule(predicate("team_id", [f"team-{i}" for i in range(32)], "in"), predicate("player_id", [f"player-{i}" for i in range(32)], "in")))
    engine.ingest(event(team_id="team-31", player_id="player-31"))
    assert engine.get(calc.calculation_id).value == 1
    engine.ingest(event(event_id="no-player-match", team_id="team-31", player_id="outside"))
    assert engine.last_candidate_count == 1
    assert engine.get(calc.calculation_id).value == 1
    engine.ingest(event(event_id="no-team-match", team_id="outside", player_id="player-31"))
    assert engine.last_candidate_count == 0


def test_time_correction_can_remove_old_contribution_without_category_change():
    engine = FilterEngine()
    calc = engine.register(rule(predicate("event_type", "corner"), predicate("match_time_seconds", 3600, "gt")))
    engine.ingest(event(match_time_seconds=3601))
    assert engine.ingest(event(revision=2, match_time_seconds=3600))[0].value == 0
    assert engine.get(calc.calculation_id).version == 3


def test_late_registration_reuses_observed_history_and_live_continues_once():
    engine = FilterEngine()
    engine.ingest(event())
    calc = engine.register(rule(predicate("event_type", "corner")), history=[event()])
    assert calc.value == 1
    assert engine.ingest(event()) == []
    assert engine.ingest(event(event_id="next"))[0].value == 2


def test_membership_numeric_identity_is_canonical():
    integer = rule(predicate("match_time_seconds", [3600, 4000], "in"))
    floating = rule(predicate("match_time_seconds", [4000.0, 3600.0], "in"))
    assert integer.calculation_id == floating.calculation_id


def test_sum_correction_retraction_and_missing_measurement():
    engine = FilterEngine()
    calc = engine.register(rule(operation="sum", sum_field="distance_metres"))
    engine.ingest(event(distance_metres=12.5))
    engine.ingest(event(revision=2, distance_metres=8.2))
    assert engine.get(calc.calculation_id).value == 8.2
    assert engine.ingest(event(event_id="missing")) == []
    engine.ingest(event(revision=3, distance_metres=8.2, deleted=True))
    assert engine.get(calc.calculation_id).value == 0


def test_decimal_sum_is_identical_for_live_history_correction_and_retraction():
    definition = rule(operation="sum", sum_field="distance_metres")
    deliveries = [event(event_id="first", distance_metres=0.1),
                  event(event_id="second", distance_metres=0.2),
                  event(event_id="second", revision=2, distance_metres=0.3),
                  event(event_id="third", distance_metres=0.00000000001)]
    live = FilterEngine()
    calc = live.register(definition)
    for delivery in deliveries:
        live.ingest(delivery)
    backfill = FilterEngine().register(definition, deliveries)
    assert live.get(calc.calculation_id).value == backfill.value == 0.40000000001
    live.ingest(event(event_id="first", revision=2, distance_metres=0.1, deleted=True))
    assert live.get(calc.calculation_id).value == 0.30000000001


def test_index_result_matches_independent_full_scan_with_many_combinations():
    rng = random.Random(42)
    engine = FilterEngine()
    definitions = []
    for _ in range(150):
        terms = []
        for field, values in [("event_type", ["corner", "shot", "pass"]), ("team_id", ["chelsea", "madrid"]), ("player_id", ["a", "b"]), ("body_part", ["head", "foot"]), ("period", [1, 2]), ("outcome", ["success", "failure"])]:
            if rng.choice([True, False]):
                terms.append(predicate(field, rng.choice(values)))
        terms.append(predicate("match_time_seconds", rng.choice([0, 2700, 3600]), "gt"))
        definition = rule(*terms)
        engine.register(definition)
        definitions.append(definition)
    latest = {}
    for index in range(100):
        item = event(event_id=str(index), event_type=rng.choice(["corner", "shot", "pass"]), team_id=rng.choice(["chelsea", "madrid"]), player_id=rng.choice(["a", "b", None]), body_part=rng.choice(["head", "foot", None]), period=rng.choice([1, 2]), outcome=rng.choice(["success", "failure"]), match_time_seconds=rng.choice([100, 3000, 4000]))
        latest[item.event_id] = item
        engine.ingest(item)
    for definition in definitions:
        expected = sum(definition.matches(e) for e in latest.values())
        assert engine.get(definition.calculation_id).value == expected


@pytest.mark.parametrize("kwargs", [
    {"field": "team_id", "op": "gt", "value": "chelsea"},
    {"field": "player_id", "op": "eq", "value": True},
    {"field": "match_time_seconds", "op": "gt", "value": "60"},
    {"field": "match_time_seconds", "op": "gt", "value": float("nan")},
    {"field": "match_time_seconds", "op": "in", "value": []},
    {"field": "period", "op": "eq", "value": 1.5},
    {"field": "unknown", "op": "eq", "value": "x"},
    {"field": "team_id", "op": "regex", "value": "x"},
    {"field": "event_type", "op": "eq", "value": "header"},
    {"field": "body_part", "op": "eq", "value": "ear"},
])
def test_reject_unsupported_or_mistyped_predicates(kwargs):
    with pytest.raises(ValidationError):
        Predicate.model_validate(kwargs)


def test_sum_requires_explicit_field_and_count_rejects_one():
    with pytest.raises(ValidationError):
        rule(operation="sum")
    with pytest.raises(ValidationError):
        rule(sum_field="distance_metres")


def test_rule_event_and_results_are_immutable():
    with pytest.raises(ValidationError):
        event().team_id = "other"
    definition = rule(predicate("event_type", "corner"))
    with pytest.raises(ValidationError):
        definition.match_id = "other"
    engine = FilterEngine()
    result = engine.register(definition)
    with pytest.raises(ValidationError):
        result.value = 12


def test_restore_delivery_version_without_replaying_old_versions():
    engine = FilterEngine()
    calc = engine.register(rule(), [event()])
    assert engine.restore_version(calc.calculation_id, 15).version == 15
    assert engine.ingest(event(event_id="next"))[0].version == 16
    with pytest.raises(ValueError):
        engine.restore_version(calc.calculation_id, 2)
