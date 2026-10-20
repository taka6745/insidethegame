"""Compact measurement contract shared by routing and stat planning."""
import re
from typing import get_args

from backend.models.events import EventType
from backend.models.rules import Predicate
from .models import GoalDecision


MEASUREMENT_POLICY = """Consult measurement_support BEFORE interpreting a measure or offering choices.
Use the supplied field meanings, record semantics and executable operations to translate everyday
wording into a useful statistic. Prefer answering the reasonable interpretation in context.
Do not interpret conversational words such as 'any' or 'all' as a demand for unobservable physical
precision. When the feed declares a suitable recorded count, use it and label the result 'Recorded'.
Preserve the user's entity, time and action scope. A recorded count excludes unclassified records;
it does not estimate them or promise exhaustive coverage. Use coverage=recorded only for the
recorded_body_part_event_groups in the contract, selecting categories within ONE group. These
groups are alternative representations, not quantities to add together. The event meanings
explain which representation covers the requested actions without duplicate contacts.
If the user explicitly needs exhaustive coverage including unrecorded/unclassified actions,
do not substitute a recorded count. If no supported interpretation answers their intent, ask one
short useful clarification or decline briefly. Missing metadata is not zero. Keep limitations short.
Clarify only when plausible interpretations would materially change the answer and context cannot
resolve them. Do not ask again after the viewer has answered. Do not repeat an unsupported option
from an older clarification. Catalogue statistics remain usable despite raw-event limitations.
A share, split, percentage, ratio or rate is never a plain event count; possession is a catalogue
share, not a count of events. When declining, name the missing data from measurement_support.unavailable.
"""

# Words naming a share or rate. A plain count/sum cannot answer them.
MEASURE_WORDS = re.compile(r'%|\b(possession|percent(?:age)?|ratio|split|share|proportion|rate|accuracy)\b', re.I)
TIME_FIELDS = ('period', 'after_seconds', 'from_seconds', 'before_seconds', 'through_seconds')


def measurement_support(reference: dict) -> dict:
    capabilities = reference.get('capabilities')
    if not capabilities:
        return {'declared': False}
    categories = sorted(set(get_args(EventType)) & set(capabilities.get('supported_event_types', ())))
    return {
        'declared': True,
        'contract_id': reference.get('contract_id'),
        'event_types': categories,
        'all_event_body_parts': bool(capabilities.get('body_parts')),
        'body_part_event_types': categories if capabilities.get('body_parts') else
            sorted(set(categories) & set(capabilities.get('body_part_event_types', ()))),
        'recorded_body_part_event_groups': [list(group) for group in
            capabilities.get('recorded_body_part_event_groups', ())
            if group and set(group) <= set(categories)],
        'distance_event_types': sorted(set(categories) & set(capabilities.get('distance_event_types', ()))),
        'shot_outcomes': bool(capabilities.get('shot_outcomes')),
        'fields': {name: value for name, value in reference.get('fields', {}).items()
                   if name in {*get_args(Predicate.model_fields['field'].annotation), 'distance_metres'}},
        'event_meanings': {kind: reference.get('events', {}).get(kind, '') for kind in categories},
        'unavailable': list(reference.get('unavailable', ())),
    }


def plain_measure(request: str, goal) -> set[str]:
    """Share/rate words a plain count or sum would misrepresent. Possession counts of
    named actions (e.g. dispossessed) stay valid; a count over every event does not."""
    if goal is None or goal.operation not in ('count', 'sum'):
        return set()
    words = {match.group(0).lower() for match in MEASURE_WORDS.finditer(f'{request} {goal.description}')}
    return words if words - {'possession'} or (words and not goal.event_types) else set()


def measure_decision(request: str, decision, context: dict):
    """Route a measure to its catalogue stat, or decline; never offer the plain count."""
    words = plain_measure(request, decision.goal) if decision.status == 'custom' else set()
    if not words:
        return decision
    goal = decision.goal
    if not goal.player_ids and all(getattr(goal, field) is None for field in TIME_FIELDS):
        # One named team selects its row; both or neither select the whole-match row.
        team = goal.team_ids[0] if len(goal.team_ids) == 1 else None
        for row in context.get('standard_stats', []):
            if row.get('team_id') == team and words & set(row['id'].split(':', 1)[-1].split('_')):
                return GoalDecision(status='reuse', standard_stat_id=row['id'])
    return GoalDecision(status='unsupported', message=(
        'Possession is a share of play, not a count of events, and no possession statistic covers that scope.'
        if 'possession' in words else
        'A percentage, ratio or rate needs two named counts; a single count of events cannot answer it.'))
