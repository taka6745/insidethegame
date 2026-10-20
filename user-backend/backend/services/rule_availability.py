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
    if getattr(rule, "composite", False):
        return any(incomplete_player_rule(item, unresolved_events) for item in rule.inputs)
    if not any(predicate.field == 'player_id' for predicate in rule.predicates):
        return False
    remaining = rule.model_copy(update={
        'predicates': tuple(predicate for predicate in rule.predicates if predicate.field != 'player_id')})
    return any(remaining.matches(event) for event in unresolved_events)


def supported_rule(rule, capabilities):
    return unsupported_reason(rule, capabilities) is None


def unsupported_reason(rule, capabilities):
    """Name the missing feed channel for a viewer, or None when the rule is answerable."""
    if getattr(rule, "composite", False):
        return next(filter(None, (unsupported_reason(item, capabilities) for item in rule.inputs)), None)
    if rule.coverage == 'recorded' and not capabilities:
        return 'This recording does not declare recorded body-part coverage.'
    if not capabilities:
        return None  # Older hand-authored fixtures declare the complete test contract.
    selected = set(get_args(EventType))
    constrained = False
    for predicate in rule.predicates:
        if predicate.field == 'event_type':
            constrained = True
            values = predicate.value if isinstance(predicate.value, tuple) else (predicate.value,)
            selected.intersection_update(values)
    supported = set(capabilities.get('supported_event_types', ()))
    names = lambda kinds: ', '.join(sorted(kinds)).replace('_', ' ')
    if constrained and not selected.issubset(supported):
        return f'This recording does not capture {names(selected - supported)} events.'
    if rule.coverage == 'recorded':
        groups = capabilities.get('recorded_body_part_event_groups', ())
        if not constrained or not selected or not any(selected <= set(group) for group in groups):
            return (f'Recorded body-part counts cover only {" or ".join(names(g) for g in groups)} events.'
                    if groups else 'This recording declares no recorded body-part counts.')
    elif any(p.field == 'body_part' for p in rule.predicates) and not capabilities.get('body_parts', False):
        covered = set(capabilities.get('body_part_event_types', ()))
        if not constrained or not selected.issubset(covered):
            return (f'This recording has body-part data only for {names(covered)} events.'
                    if covered else 'This recording has no body-part data.')
    if rule.operation in {'sum', 'count_present'} and not selected.issubset(set(capabilities.get('distance_event_types', ()))):
        distances = capabilities.get('distance_event_types', ())
        return (f'This recording has distance data only for {names(distances)} events.'
                if distances else 'This recording has no distance data.')
    if any(p.field == 'outcome' for p in rule.predicates):
        if 'shot' in selected and not capabilities.get('shot_outcomes', False):
            return 'This recording has no shot outcomes.'
    return None
