"""A missing telemetry channel is unknown, not a zero-valued statistic."""
from typing import get_args
from backend.models.events import EventType


def supported_rule(rule, capabilities):
    if not capabilities:
        return True  # Older hand-authored fixtures declare the complete test contract.
    selected = set(get_args(EventType))
    constrained = False
    for predicate in rule.predicates:
        if predicate.field == 'event_type':
            constrained = True
            values = predicate.value if isinstance(predicate.value, tuple) else (predicate.value,)
            selected.intersection_update(values)
        if predicate.field == 'body_part' and not capabilities.get('body_parts', False):
            return False
    supported = set(capabilities.get('supported_event_types', ()))
    if constrained and not selected.issubset(supported):
        return False
    if rule.operation == 'sum' and not selected.issubset(set(capabilities.get('distance_event_types', ()))):
        return False
    if any(p.field == 'outcome' for p in rule.predicates):
        if 'shot' in selected and not capabilities.get('shot_outcomes', False):
            return False
    return True
