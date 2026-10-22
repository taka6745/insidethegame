"""A missing feed channel is unknown, not a zero-valued statistic.

Every SPADL action type is available (ETL converts MA3); body parts, shot outcomes and locations depend
on what the match's MA1 capabilities declare, as ETL's catalogue `requires` does. A match that declares
no capabilities has none of them: they are unknown, never assumed complete."""
from typing import get_args

from backend.models.actions import ActionType, PASS_FAMILY, SHOT_FAMILY

# MA1 body-part capability names (provider categories) -> the SPADL types they cover.
BODY_PART_FAMILIES = {'pass': PASS_FAMILY, 'shot': SHOT_FAMILY, 'goal': SHOT_FAMILY}


def observed_unattributed_events(actions):
    """Actions without a player in the observed prefix."""
    return tuple(action for action in actions if action.player_id is None)


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


def body_part_types(capabilities):
    """SPADL types whose body part is classified for every action (complete counts)."""
    if capabilities.get('body_parts'):
        return set(get_args(ActionType))
    return {kind for name in capabilities.get('body_part_event_types', ()) for kind in BODY_PART_FAMILIES.get(name, ())}


UNDECLARED = "This match's feed declares no capabilities, so its body parts, shot outcomes and locations are unknown."


def unsupported_reason(rule, capabilities):
    """Name the missing feed channel for a viewer, or None when the rule is answerable. capabilities: the
    MA1 declaration (snake_case), or None when the match declares none."""
    if getattr(rule, "composite", False):
        return next(filter(None, (unsupported_reason(item, capabilities) for item in rule.inputs)), None)
    reason = _missing(rule, capabilities or {})
    return UNDECLARED if reason and capabilities is None else reason


def _missing(rule, capabilities):
    selected = set(get_args(ActionType))
    for predicate in rule.predicates:
        if predicate.field == 'action_type':
            selected &= set(predicate.value if isinstance(predicate.value, tuple) else (predicate.value,))
    names = lambda kinds: ', '.join(sorted(kinds)).replace('_', ' ')
    covered = body_part_types(capabilities)
    if rule.coverage == 'recorded':
        if not covered:
            return 'This recording has no body-part data.'
    elif any(p.field == 'bodypart' for p in rule.predicates) and not selected <= covered:
        return (f'This recording classifies body parts only for {names(covered)} actions; '
                'ask for a recorded count instead.' if covered else 'This recording has no body-part data.')
    if any(p.field == 'shot_outcome' for p in rule.predicates) and not capabilities.get('shot_outcomes', False):
        return 'This recording has no shot outcomes.'
    uses_location = rule.operation in {'sum', 'count_present'} or any(
        p.field in {'start_x', 'start_y', 'end_x', 'end_y', 'start_zone', 'end_zone'} for p in rule.predicates)
    if uses_location and not capabilities.get('coordinates'):
        return 'This recording has no action locations.'
    return None
