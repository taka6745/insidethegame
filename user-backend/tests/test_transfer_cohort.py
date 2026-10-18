"""No model calls: preserve transfer cohort scope and independent gold answers."""
import json

from backend.adapters.events import OptaInspiredAdapter
from benchmarks.balanced_cases import INTENTS
from benchmarks.cases import cases
from benchmarks.correctness import COHORTS, FIXTURE, gold_check
from benchmarks.transfer_cases import REQUESTS, transfer_cases


def test_transfer_is_twelve_distinct_additional_intents_with_short_replies():
    selected = transfer_cases()
    original = cases()
    assert len(selected) == len({row['id'] for row in selected}) == 12
    assert not {row[0] for row in REQUESTS} & {row[0] for row in INTENTS}
    for row, (number, _, _) in zip(selected, REQUESTS):
        gold = original[number - 1]
        assert row['expected_rule'] == gold['expected_rule']
        assert row['expected_weights'] == gold['expected_weights']
        assert row['prompt'] != gold['prompt']
        assert row['expected_status'] == ['ready'] and not row['must_clarify']
        assert len(row['replies']) == 1 and len(row['replies'][0]) < 100
    assert COHORTS['transfer']() == selected


def test_transfer_gold_matches_every_revision_and_backfill():
    scenario = json.loads(FIXTURE.read_text())
    events = [OptaInspiredAdapter().adapt(raw) for raw in scenario['events']]
    results = gold_check(scenario, events, transfer_cases())
    assert len(results) == 12 and all(row['ok'] for row in results)
