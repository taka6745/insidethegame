"""The agents' data reference for one match: the SPADL dictionary plus what this match's feed
declares (MA1 capabilities). No recording is read."""
from backend.services.rule_availability import body_part_types

from backend.adapters.feed_reference import reference

CAPABILITIES = ('body_parts', 'body_part_event_types', 'shot_outcomes', 'coordinates', 'periods')


def data_reference(capabilities):
    """capabilities: snake_case (adapters/ma3.py), or None when MA1 declares none: then no channel is listed
    as available and rule_availability refuses every rule that needs one."""
    data = reference()
    if capabilities:
        # Only what rules depend on; the provider's own event vocabulary is not SPADL's.
        data['capabilities'] = {key: capabilities[key] for key in CAPABILITIES if key in capabilities}
        covered = sorted(body_part_types(capabilities))
        data['availability'] = {
            'complete_bodypart_types': covered,
            'recorded_bodyparts': bool(covered),
            'shot_outcomes': bool(capabilities.get('shot_outcomes')),
            'locations': bool(capabilities.get('coordinates'))}
        if covered and len(covered) < len(data['events']):
            data['guarantees'] = [*data['guarantees'],
                f"Body parts are classified for {', '.join(covered)} only. For other types a body part is the "
                "default unless bodypart_observed; count those with coverage=recorded and label the result Recorded."]
    return data
