import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.doubles.events import OptaInspiredAdapter

SCENARIO = json.loads((Path(__file__).parents[1] / "fixtures/filter-lab.json").read_text())


def test_named_qualifiers_map_without_vendor_numeric_ids():
    event = OptaInspiredAdapter().adapt(SCENARIO["events"][0])
    assert event.event_id == "e1"
    assert event.body_part == "head"
    assert event.distance_metres == 8
    assert event.match_time_seconds == 120
    assert event.player_id == "mbappe"


def test_period_disambiguates_first_half_added_time_from_second_half():
    adapter = OptaInspiredAdapter()
    first = adapter.adapt(next(e for e in SCENARIO["events"] if e["eventId"] == "e8"))
    second = adapter.adapt(next(e for e in SCENARIO["events"] if e["eventId"] == "e9"))
    assert first.match_time_seconds == second.match_time_seconds == 2760
    assert (first.period, second.period) == (1, 2)


@pytest.mark.parametrize("changes", [
    {"timeSec": 60}, {"timeMin": -1}, {"periodId": 0},
    {"revision": 0}, {"synthetic": False}, {"typeName": "not-supported"},
    {"qualifiers": [{"type": "bodyPart", "value": "head"}, {"type": "bodyPart", "value": "foot"}]},
    {"qualifiers": [{"type": "distanceMetres", "value": "8"}]},
    {"qualifiers": [{"type": "distanceMetres", "value": float("inf")}]},
    {"qualifiers": [{"type": "bodyPart", "value": "ear"}]},
])
def test_malformed_fixture_fails_at_adapter_boundary(changes):
    with pytest.raises(ValidationError):
        OptaInspiredAdapter().adapt(SCENARIO["events"][0] | changes)


def test_extra_vendor_fields_require_deliberate_adapter_mapping():
    with pytest.raises(ValidationError):
        OptaInspiredAdapter().adapt(SCENARIO["events"][0] | {"typeId": 1})


@pytest.mark.parametrize('kind', [
    'throw_in', 'free_kick', 'goal_kick', 'kick_off', 'penalty', 'offside',
    'foul_won', 'keeper_claim', 'period_start', 'period_end',
])
def test_native_event_categories_are_accepted_and_extra_qualifiers_stay_upstream(kind):
    # Canonical events give the clock and ticker; custom rules filter SPADL actions, not these categories.
    raw = SCENARIO['events'][0] | {'typeName': kind, 'qualifiers': [
        {'type': 'restartType', 'value': 'corner'},
        {'type': 'relatedEventId', 'value': 'native-20'},
    ]}
    event = OptaInspiredAdapter().adapt(raw)
    assert event.event_type == kind
    assert 'restartType' not in event.model_dump() and 'restartType' not in event.qualifiers
    assert event.qualifiers['relatedEventId'] == 'native-20'


@pytest.mark.parametrize('outcome', ['yellow', 'second_yellow', 'red'])
def test_native_card_outcomes_keep_recipient_and_decision(outcome):
    event = OptaInspiredAdapter().adapt(SCENARIO['events'][0] | {'typeName': 'card', 'outcome': outcome})
    assert event.player_id == 'mbappe'
    assert event.outcome == outcome
