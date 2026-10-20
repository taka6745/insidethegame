"""Independent full-match reference check for 100 generated rules, without models."""
import json
from pathlib import Path

from backend.services.filter_engine import FilterEngine
from .performance import DEFAULT_RECORDING, generated_rule, load, reference_total, templates


def main():
    recording, events = load(DEFAULT_RECORDING)
    keys, engine, rules = templates(events), FilterEngine(), []
    for i in range(100):
        rule = generated_rule(i * 127, recording['match_id'], 'selective' if i % 2 else 'overlapping', keys)
        rules.append(rule)
        engine.register(rule)
    for event in events:
        engine.ingest(event)
    for rule in rules:
        assert engine.get(rule.calculation_id).value == reference_total(rule, events), rule.calculation_id
    result = {'rules_checked': len(rules), 'deliveries': len(events), 'passed': True,
              'scope': 'Final full-match totals against independent scalar interpreter; no model calls'}
    path = Path('.local/benchmarks/full-match.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
