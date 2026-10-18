"""A missing telemetry channel is unknown, not a zero-valued statistic."""
from typing import get_args
from backend.models.events import EventType


def observed_unattributed_events(history):
    """Unknown players in the observed prefix, after corrections and retractions."""
    latest = {}
    for event in history:
        key = event.match_id, event.event_id
        if key not in latest or event.revision > latest[key].revision:
            latest[key] = event
    return tuple(event for event in latest.values() if event.player_id is None and not event.deleted)


def incomplete_player_rule(rule, unresolved_events):
    """An unattributed matching action may belong to the requested player."""
    if not any(predicate.field == 'player_id' for predicate in rule.predicates):
        return False
    remaining = rule.model_copy(update={
        'predicates': tuple(predicate for predicate in rule.predicates if predicate.field != 'player_id')})
    return any(remaining.matches(event) for event in unresolved_events)


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
    supported = set(capabilities.get('supported_event_types', ()))
    if constrained and not selected.issubset(supported):
        return False
    if any(p.field == 'body_part' for p in rule.predicates) and not capabilities.get('body_parts', False):
        covered = set(capabilities.get('body_part_event_types', ()))
        if not constrained or not selected.issubset(covered):
            return False
    if rule.operation == 'sum' and not selected.issubset(set(capabilities.get('distance_event_types', ()))):
        return False
    if any(p.field == 'outcome' for p in rule.predicates):
        if 'shot' in selected and not capabilities.get('shot_outcomes', False):
            return False
    return True
