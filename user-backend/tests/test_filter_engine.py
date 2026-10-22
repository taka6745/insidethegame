"""Reference values, final-action semantics and bounded candidate-work tests over SPADL actions."""
import json
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.doubles.events import OptaInspiredAdapter
from backend.models.actions import SpadlAction
from backend.models.rules import Predicate, Rule
from backend.services.filter_engine import FilterEngine
from benchmarks.doubles.spadl import actions_from_events

SCENARIO = json.loads((Path(__file__).parents[1] / "fixtures/filter-lab.json").read_text())
DEFAULT = {"match_id": "match", "action_id": 1, "action_type": "corner_crossed", "result": "success",
           "bodypart": "foot", "team_id": "riverton", "match_time_seconds": 4025, "period": 2, "start_x": 50.0,
           "start_y": 34.0, "end_x": 50.0, "end_y": 34.0, "start_zone": "middle_third", "end_zone": "middle_third",
           "seq": 1, "final_seq": 1}


def action(**changes):
    return SpadlAction(**(DEFAULT | changes))


def rule(*predicates, **changes):
    return Rule(match_id="match", predicates=predicates, **changes)


def predicate(field, value, op="eq"):
    return Predicate(field=field, op=op, value=value)


def scenario_actions():
    events = [OptaInspiredAdapter().adapt(raw) for raw in SCENARIO["events"]]
    home = SCENARIO["teams"][0]["id"]
    return [SpadlAction.from_row(row, SCENARIO["match_id"], home) for row in actions_from_events(events, home)]


@pytest.mark.parametrize("preset", SCENARIO["presets"], ids=lambda p: p["id"])
def test_examples_from_natural_requests(preset):
    engine, actions = FilterEngine(), scenario_actions()
    definition = Rule.model_validate(preset["rule"])
    identifier = engine.register(definition).calculation_id
    for item in actions:
        engine.ingest(item)
    assert engine.get(identifier).value == preset["expected_final"]
    # Late registration over the same actions yields the same value.
    assert FilterEngine().register(definition, actions).value == preset["expected_final"]


def test_boundary_60_minutes_is_strict_and_teamless_rule_still_matches():
    engine = FilterEngine()
    strict = engine.register(rule(predicate("action_type", "corner_crossed"), predicate("match_time_seconds", 3600, "gt")))
    inclusive = engine.register(rule(predicate("action_type", "corner_crossed"), predicate("match_time_seconds", 3600, "gte")))
    engine.ingest(action(match_time_seconds=3600))
    assert engine.get(strict.calculation_id).value == 0
    assert engine.get(inclusive.calculation_id).value == 1
    engine.ingest(action(action_id=2, match_time_seconds=3601, team_id="madrid"))
    assert engine.get(strict.calculation_id).value == 1
    assert engine.get(inclusive.calculation_id).value == 2


def test_100k_unique_filters_do_not_mean_100k_lookups():
    engine = FilterEngine()
    for index in range(100_000):
        engine.register(rule(predicate("action_type", "shot"), predicate("player_id", f"player-{index}")))
    broad = engine.register(rule(predicate("match_time_seconds", 3600, "gt")))
    corner = engine.register(rule(predicate("action_type", "corner_crossed")))
    changes = engine.ingest(action())
    assert {r.calculation_id for r in changes} == {broad.calculation_id, corner.calculation_id}
    assert engine.last_candidate_count == 2
    assert engine.last_index_probe_count == 64
    engine.ingest(action(action_id=2, action_type="shot", player_id="player-4321"))
    assert engine.last_candidate_count == 2  # one player rule and the broad rule


def test_duplicate_and_conflicting_final_action():
    engine = FilterEngine()
    calc = engine.register(rule())
    first = engine.ingest(action())[0]
    assert engine.ingest(action()) == []
    assert engine.last_candidate_count == 0
    with pytest.raises(ValueError, match="Conflicting"):
        engine.ingest(action(team_id="madrid"))
    assert engine.get(calc.calculation_id) == first


def test_equivalent_rules_reuse_id_despite_order_membership_and_duplicates():
    a = rule(predicate("team_id", "riverton"), predicate("action_type", ["shot", "shot_penalty"], "in"))
    b = rule(predicate("action_type", ["shot_penalty", "shot", "shot_penalty"], "in"),
             predicate("team_id", ["riverton"], "in"), predicate("team_id", "riverton"))
    engine = FilterEngine()
    assert engine.register(a).calculation_id == engine.register(b).calculation_id
    assert engine.count == 1


def test_matches_are_namespaced_and_missing_optional_fields_are_not_matches():
    engine = FilterEngine()
    calc = engine.register(rule(predicate("player_id", "mbappe")))
    assert engine.ingest(action(match_id="other", player_id="mbappe")) == []
    assert engine.ingest(action(player_id=None)) == []
    assert engine.get(calc.calculation_id).value == 0


def test_membership_intersection_and_contradictory_rules():
    engine = FilterEngine()
    calc = engine.register(rule(predicate("action_type", ["corner_crossed", "shot"], "in"),
                                predicate("action_type", "corner_crossed")))
    impossible = engine.register(rule(predicate("team_id", "riverton"), predicate("team_id", "madrid")))
    engine.ingest(action())
    assert engine.get(calc.calculation_id).value == 1
    assert engine.get(impossible.calculation_id).value == 0
    assert engine.last_candidate_count == 1


def test_membership_compound_index_and_bounded_expansion():
    engine = FilterEngine()
    # 32 x 32 combinations would explode registration. The engine indexes only
    # a bounded subset and applies remaining predicates to candidate actions.
    calc = engine.register(rule(predicate("team_id", [f"team-{i}" for i in range(32)], "in"),
                                predicate("player_id", [f"player-{i}" for i in range(32)], "in")))
    engine.ingest(action(team_id="team-31", player_id="player-31"))
    assert engine.get(calc.calculation_id).value == 1
    engine.ingest(action(action_id=2, team_id="team-31", player_id="outside"))
    assert engine.last_candidate_count == 1
    assert engine.get(calc.calculation_id).value == 1
    engine.ingest(action(action_id=3, team_id="outside", player_id="player-31"))
    assert engine.last_candidate_count == 0


def test_zone_location_and_shot_outcome_predicates():
    engine = FilterEngine()
    box = engine.register(rule(predicate("end_zone", "opp_box")))
    deep = engine.register(rule(predicate("end_x", 90, "gte"), predicate("end_y", 20, "gte"), predicate("end_y", 48, "lte")))
    saved = engine.register(rule(predicate("action_type", "shot"), predicate("shot_outcome", "saved")))
    engine.ingest(action(action_type="shot", result="fail", source_type_id=15, end_x=105.0, end_zone="opp_box"))
    engine.ingest(action(action_id=2, action_type="shot", result="fail", source_type_id=15, end_x=95.0, end_zone="opp_box"))
    engine.ingest(action(action_id=3, end_x=100.0, end_y=10.0, end_zone="final_third"))
    assert [engine.get(c.calculation_id).value for c in (box, deep, saved)] == [2, 2, 1]


def test_recorded_coverage_counts_only_observed_body_parts():
    engine = FilterEngine()
    complete = engine.register(rule(predicate("bodypart", "head")))
    recorded = engine.register(rule(predicate("bodypart", "head"), coverage="recorded"))
    engine.ingest(action(bodypart="head", bodypart_observed=True))
    engine.ingest(action(action_id=2, bodypart="head", bodypart_observed=False))
    assert engine.get(complete.calculation_id).value == 2
    assert engine.get(recorded.calculation_id).value == 1


def test_late_registration_reuses_observed_history_and_live_continues_once():
    engine = FilterEngine()
    engine.ingest(action())
    calc = engine.register(rule(predicate("action_type", "corner_crossed")), history=[action()])
    assert calc.value == 1
    assert engine.ingest(action()) == []
    assert engine.ingest(action(action_id=2))[0].value == 2


def test_membership_numeric_identity_is_canonical():
    integer = rule(predicate("match_time_seconds", [3600, 4000], "in"))
    floating = rule(predicate("match_time_seconds", [4000.0, 3600.0], "in"))
    assert integer.calculation_id == floating.calculation_id


def test_sum_of_ball_distance():
    engine = FilterEngine()
    calc = engine.register(rule(operation="sum", sum_field="distance_metres"))
    engine.ingest(action(start_x=10.0, start_y=10.0, end_x=13.0, end_y=14.0))
    assert engine.get(calc.calculation_id).value == 5.0
    engine.ingest(action(action_id=2))  # Zero length still counts as zero metres.
    assert engine.get(calc.calculation_id).value == 5.0


def test_decimal_sum_is_identical_for_live_and_history():
    definition = rule(operation="sum", sum_field="distance_metres")
    deliveries = [action(action_id=1, start_x=0.0, end_x=0.1), action(action_id=2, start_x=0.0, end_x=0.2),
                  action(action_id=3, start_x=0.0, end_x=0.00000000001)]
    live = FilterEngine()
    calc = live.register(definition)
    for delivery in deliveries:
        live.ingest(delivery)
    backfill = FilterEngine().register(definition, deliveries)
    assert live.get(calc.calculation_id).value == backfill.value == 0.30000000001


def test_index_result_matches_independent_full_scan_with_many_combinations():
    rng = random.Random(42)
    engine = FilterEngine()
    definitions = []
    choices = [("action_type", ["corner_crossed", "shot", "pass"]), ("team_id", ["riverton", "madrid"]),
               ("player_id", ["a", "b"]), ("bodypart", ["head", "foot"]), ("period", [1, 2]),
               ("result", ["success", "fail"]), ("end_zone", ["opp_box", "middle_third"])]
    for _ in range(150):
        terms = [predicate(field, rng.choice(values)) for field, values in choices if rng.choice([True, False])]
        terms.append(predicate("match_time_seconds", rng.choice([0, 2700, 3600]), "gt"))
        definition = rule(*terms)
        engine.register(definition)
        definitions.append(definition)
    actions = []
    for index in range(100):
        item = action(action_id=index, action_type=rng.choice(["corner_crossed", "shot", "pass"]),
                      team_id=rng.choice(["riverton", "madrid"]), player_id=rng.choice(["a", "b", None]),
                      bodypart=rng.choice(["head", "foot"]), period=rng.choice([1, 2]),
                      result=rng.choice(["success", "fail"]), end_zone=rng.choice(["opp_box", "middle_third"]),
                      match_time_seconds=rng.choice([100, 3000, 4000]))
        actions.append(item)
        engine.ingest(item)
    for definition in definitions:
        assert engine.get(definition.calculation_id).value == sum(definition.matches(a) for a in actions)


@pytest.mark.parametrize("kwargs", [
    {"field": "team_id", "op": "gt", "value": "riverton"},
    {"field": "player_id", "op": "eq", "value": True},
    {"field": "match_time_seconds", "op": "gt", "value": "60"},
    {"field": "match_time_seconds", "op": "gt", "value": float("nan")},
    {"field": "match_time_seconds", "op": "in", "value": []},
    {"field": "period", "op": "eq", "value": 1.5},
    {"field": "unknown", "op": "eq", "value": "x"},
    {"field": "team_id", "op": "regex", "value": "x"},
    {"field": "action_type", "op": "eq", "value": "header"},
    {"field": "event_type", "op": "eq", "value": "pass"},
    {"field": "bodypart", "op": "eq", "value": "ear"},
    {"field": "end_zone", "op": "eq", "value": "wing"},
    {"field": "end_x", "op": "gt", "value": 106},
    {"field": "start_y", "op": "lt", "value": 69},
])
def test_reject_unsupported_or_mistyped_predicates(kwargs):
    with pytest.raises(ValidationError):
        Predicate.model_validate(kwargs)


def test_sum_requires_explicit_field_and_count_rejects_one():
    with pytest.raises(ValidationError):
        rule(operation="sum")
    with pytest.raises(ValidationError):
        rule(sum_field="distance_metres")


def test_rule_action_and_results_are_immutable():
    with pytest.raises(ValidationError):
        action().team_id = "other"
    definition = rule(predicate("action_type", "corner_crossed"))
    with pytest.raises(ValidationError):
        definition.match_id = "other"
    result = FilterEngine().register(definition)
    with pytest.raises(ValidationError):
        result.value = 12


def test_restore_delivery_version_without_replaying_old_versions():
    engine = FilterEngine()
    calc = engine.register(rule(), [action()])
    assert engine.restore_version(calc.calculation_id, 15).version == 15
    assert engine.ingest(action(action_id=2))[0].version == 16
    with pytest.raises(ValueError):
        engine.restore_version(calc.calculation_id, 2)


def test_formula_stats_from_the_team_review_evaluate_exactly():
    """PLAN.md §12 M9: 'take-ons in their own half' (a location bound) and 'pass success rate' (a percentage of two
    counts) compile to rules whose values match an independent scan of the same SPADL actions."""
    from backend.agents.models import Goal, LocationBound

    team = "riverton"
    actions = [action(action_id=i + 1, action_type=kind, result=result, start_x=x, team_id=side)
               for i, (kind, result, x, side) in enumerate([
                   ("take_on", "success", 30.0, team), ("take_on", "fail", 52.5, team), ("take_on", "success", 70.0, team),
                   ("take_on", "success", 20.0, "madrid"), ("pass", "success", 40.0, team), ("pass", "success", 60.0, team),
                   ("pass", "fail", 80.0, team), ("pass", "success", 50.0, "madrid")])]
    own_half = Goal(description="take-ons in own half", action_types=("take_on",), team_ids=(team,),
                    locations=(LocationBound(field="start_x", lte=52.5),))
    passes = dict(action_types=("pass",), team_ids=(team,))
    rate = Goal(description="pass success rate", operation="percentage", inputs=(
        Goal(description="completed passes", results=("success",), **passes), Goal(description="passes", **passes)))
    engine = FilterEngine()
    ids = [engine.register(goal.target_rule("match")).calculation_id for goal in (own_half, rate)]
    for item in actions:
        engine.ingest(item)
    mine = [a for a in actions if a.team_id == team]
    takeons = sum(1 for a in mine if a.action_type == "take_on" and a.start_x <= 52.5)
    made = [a for a in mine if a.action_type == "pass"]
    assert engine.get(ids[0]).value == takeons == 2
    assert float(engine.get(ids[1]).value) == pytest.approx(100 * sum(a.result == "success" for a in made) / len(made))
