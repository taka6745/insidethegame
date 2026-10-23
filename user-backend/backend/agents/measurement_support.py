"""Compact measurement contract shared by routing and stat planning."""
import re
from typing import get_args

from backend.models.rules import PredicateField
from backend.agents.models import GoalDecision


MEASUREMENT_POLICY = """Consult measurement_support and the SPADL data reference BEFORE interpreting a measure or offering
choices. Every statistic is defined on SPADL actions (type, result, body part, team-relative zones and
locations); translate everyday wording into those values. Prefer answering the reasonable interpretation.
Do not read conversational words such as 'any' or 'all' as a demand for unobservable precision.
Body parts are complete only for measurement_support.complete_bodypart_types; for other types count
coverage=recorded (only actions whose body part the provider named) and label the result 'Recorded'.
Preserve the user's entity, time and action scope. Missing metadata is not zero.
Clarify only when plausible interpretations would materially change the answer and context cannot
resolve them. Do not ask again after the viewer has answered. Do not repeat an unsupported option
from an older clarification. Catalogue statistics remain usable.
A share, split, percentage, ratio or rate is never a plain count; possession is a catalogue share,
not a count of actions. Cards are outside SPADL: use the cards catalogue stat. When declining, name the
missing data from measurement_support.unavailable.
Saves mean goalkeeper saves: use the shots_saved catalogue stat (custom: keeper_save with save_kinds [save]).
The saves stat also counts outfield blocks and keeper touches of shots going wide; use it only when asked
for every save event.
"""

# Words naming a share or rate. A plain count/sum cannot answer them.
MEASURE_WORDS = re.compile(r'%|\b(possession|percent(?:age)?|ratio|split|share|proportion|rate|accuracy)\b', re.I)
TIME_FIELDS = ('period', 'after_seconds', 'from_seconds', 'before_seconds', 'through_seconds')


def measurement_support(reference: dict) -> dict:
    """What this match's feed lets a custom calculation select (meanings are in the data reference)."""
    availability = reference.get('availability')
    if not availability:
        return {'declared': False}
    return {'declared': True, 'contract_id': reference.get('contract_id'), **availability,
            'filters': list(get_args(PredicateField)), 'sum_fields': ['distance_metres'],
            'unavailable': [*reference.get('unavailable', ()), *reference.get('outside_spadl', ())]}


def plain_measure(request: str, goal) -> set[str]:
    """Share/rate words a plain count or sum would misrepresent. Possession counts of
    named actions (e.g. dispossessed) stay valid; a count over every event does not."""
    if goal is None or goal.operation not in ('count', 'sum'):
        return set()
    words = {match.group(0).lower() for match in MEASURE_WORDS.finditer(f'{request} {goal.description}')}
    if words == {'split'} and goal.action_types and goal.operation == 'count':
        return set()  # "Shots split per team" is each team's count (question_tools.per_team), not a share.
    return words if words - {'possession'} or (words and not goal.action_types) else set()


# "Saves" means goalkeeper saves unless the viewer asks for every save event (blocks, wide touches).
EVERY_SAVE = re.compile(r'\b(block\w*|wide|off[ -]target|every|all save|save events?|keeper_save|including)\b', re.I)


def real_save_id(request: str, stat_id: str, known) -> str:
    """A plain 'saves' catalogue id becomes its shots_saved row (when that row exists)."""
    if EVERY_SAVE.search(request) or not stat_id.endswith(':saves'):
        return stat_id
    swapped = f'{stat_id[:-len(":saves")]}:shots_saved'
    return swapped if swapped in known else stat_id


def real_saves(request: str, decision, context: dict):
    """A plain 'saves' request reads real goalkeeper saves: catalogue shots_saved, or save_kind save."""
    if EVERY_SAVE.search(request):
        return decision
    if decision.status == 'reuse':
        known = {row['id'] for row in context.get('standard_stats', [])}
        ids = [real_save_id(request, i, known) for i in decision.standard_stat_ids]
        return decision if ids == decision.standard_stat_ids else decision.model_copy(
            update={'standard_stat_ids': ids, 'standard_stat_id': ids[0]})
    goals = [decision.goal, *getattr(decision.goal, 'inputs', ())] if decision.status == 'custom' else []
    if any(g.action_types == ('keeper_save',) and not g.save_kinds for g in goals):
        fix = lambda g: g.model_copy(update={'save_kinds': ('save',)}) \
            if g.action_types == ('keeper_save',) and not g.save_kinds else g
        goal = fix(decision.goal)
        if getattr(goal, 'inputs', None):
            goal = goal.model_copy(update={'inputs': tuple(fix(g) for g in goal.inputs)})
        return decision.model_copy(update={'goal': goal})
    return decision


def measure_decision(request: str, decision, context: dict):
    """Route a measure to its catalogue stat, or decline; never offer the plain count."""
    decision = real_saves(request, decision, context)
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
