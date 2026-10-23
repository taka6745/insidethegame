"""The agent corpora on SPADL: gold rules translated with the saved-rule vocabulary map (cards and touches become
expected refusals or reuse); an action carries its source event's latest-revision weight."""
import importlib.util
from decimal import Decimal
from functools import cache
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / 'migrations' / '020_spadl_rules.py'


@cache
def _migration():
    spec = importlib.util.spec_from_file_location('migration_020_spadl_rules', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def translate(rule):
    """Old rule JSON -> (SPADL rule JSON, None) or (None, reason)."""
    migration = _migration()
    try:
        return migration.convert(rule).model_dump(mode='json'), None
    except migration.Unsupported as exc:
        return None, str(exc)


def fixture_actions(events, home):
    """Canonical fixture events -> SpadlAction list through the SPADL double."""
    from backend.models.actions import SpadlAction
    from benchmarks.doubles.spadl import actions_from_events
    return [SpadlAction.from_row(row, events[0].match_id, home) for row in actions_from_events(list(events), home)]


def expected_trace(case, actions, deliveries):
    """Hand-written weight sum per delivery prefix: actions final by that seq, latest revision weights."""
    latest = {}
    for event in deliveries:
        latest[event['eventId']] = max(latest.get(event['eventId'], 0), event['revision'])
    weight = lambda action: Decimal(str(case['expected_weights'].get(
        f"{action.source_event_id}@{latest.get(action.source_event_id, 1)}", 0)))
    return [float(sum((weight(a) for a in actions if a.final_seq <= seq), Decimal(0)))
            for seq in range(1, len(deliveries) + 1)]
