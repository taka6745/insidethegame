"""No model calls: preserve transfer cohort scope and independent gold answers."""
import json

from benchmarks.doubles.events import OptaInspiredAdapter
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
        assert row.get('expected_rule') == gold.get('expected_rule')
        assert row.get('expected_weights') == gold.get('expected_weights')
        assert row['prompt'] != gold['prompt']
        # Intents SPADL cannot express (cards) are expected refusals or catalogue reuse.
        assert row['expected_status'] == (['ready'] if 'expected_rule' in gold else ['unsupported', 'reuse'])
        assert not row['must_clarify']
        assert len(row['replies']) == 1 and len(row['replies'][0]) < 100
    assert COHORTS['transfer']() == selected


def test_transfer_gold_matches_every_revision_and_backfill():
    scenario = json.loads(FIXTURE.read_text())
    events = [OptaInspiredAdapter().adapt(raw) for raw in scenario['events']]
    results = gold_check(scenario, events, transfer_cases())
    assert len(results) == sum('expected_rule' in row for row in transfer_cases()) == 10
    assert all(row['ok'] for row in results)
