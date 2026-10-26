"""Custom rules move from canonical events to SPADL actions.

Old rules filtered MatchEvent v2 fields (event_type, outcome, body_part); new rules filter SPADL
(action_type, result, bodypart, shot_outcome, zones). This migration
- seeds `rule_vocabulary_map`, the old → SPADL mapping (also README.md, Models);
- rewrites each saved calculation and its tracked offers to the SPADL rule and new calculation_id,
  recording old → new in `calculation_id_map` so tracked cards follow;
- keeps a rule with no SPADL equivalent (touches, cards, aerials, ...) as an unavailable tracked card:
  its offers get `unsupported` with the reason, and the calculation row is removed.
Saved values are recounted from ETL's SPADL actions when each match next loads.
"""
from psycopg.types.json import Jsonb

PASS = ['pass', 'cross', 'throw_in', 'freekick_crossed', 'freekick_short', 'corner_crossed', 'corner_short', 'goalkick']
SHOTS = ['shot', 'shot_penalty', 'shot_freekick']
# old event_type -> (SPADL action types, extra predicate or None, note); types None = no SPADL equivalent.
EVENT_TYPES = {
    'pass': (PASS, None, 'Pass family, as the catalogue counts passes.'),
    'shot': (SHOTS, {'field': 'result', 'op': 'eq', 'value': 'fail'}, 'Old shots excluded goals.'),
    'goal': (SHOTS, {'field': 'result', 'op': 'eq', 'value': 'success'}, 'Own goals are bad_touch + owngoal.'),
    'corner': (['corner_crossed', 'corner_short'], None, 'Corners taken.'),
    'save': (['keeper_save'], None, 'SPADL counts every Opta save, including blocks.'),
    'tackle': (['tackle'], None, ''),
    'clearance': (['clearance'], None, ''),
    'interception': (['interception'], None, 'Now includes blocked passes.'),
    'blocked_pass': (['interception'], None, 'SPADL merges blocked passes into interception.'),
    'foul': (['foul'], None, ''),
    'throw_in': (['throw_in'], None, ''),
    'free_kick': (['freekick_crossed', 'freekick_short', 'shot_freekick'], None, 'Free kicks taken.'),
    'goal_kick': (['goalkick'], None, ''),
    'penalty': (['shot_penalty'], None, 'Penalty kicks taken.'),
    'offside': (PASS, {'field': 'result', 'op': 'eq', 'value': 'offside'}, 'The offside pass, credited to the passer.'),
    'keeper_claim': (['keeper_claim'], None, ''),
    'keeper_pickup': (['keeper_pick_up'], None, ''),
    'punch': (['keeper_punch'], None, ''),
    'take_on': (['take_on'], None, ''),
    'ball_touch': (['bad_touch'], None, 'Unsuccessful ball touches.'),
    **{kind: (None, None, reason) for kind, reason in {
        'touch': 'SPADL has no touch action.', 'card': 'Cards are outside SPADL; use the cards stat.',
        'aerial': 'SPADL has no aerial duel action.', 'ball_recovery': 'SPADL turns recoveries into dribbles.',
        'kick_off': 'A SPADL kick-off is a pass.', 'foul_won': 'SPADL records only the offender.',
        'dispossessed': 'SPADL has no dispossession action.', 'challenge': 'SPADL has no challenge action.',
        'out': 'Ball out of play is not an action.', 'corner_awarded': 'Corner awards are not actions.',
        'offside_provoked': 'Not an action.', 'error': 'Not an action.', 'period_start': 'Not an action.',
        'period_end': 'Not an action.'}.items()}}
OUTCOMES = {'success': ('result', 'success'), 'failure': ('result', 'fail'), 'saved': ('shot_outcome', 'saved'),
            'off_target': ('shot_outcome', 'off_target'), 'post': ('shot_outcome', 'post'),
            'blocked': ('shot_outcome', 'blocked')}  # red/yellow/second_yellow: cards, unsupported.
BODY_PARTS = {'head': ['head'], 'left_foot': ['foot_left'], 'right_foot': ['foot_right'],
              'foot': ['foot', 'foot_left', 'foot_right'], 'other': ['other'], 'hand': ['other']}
KEPT = {'team_id', 'player_id', 'period', 'match_time_seconds'}


class Unsupported(ValueError):
    pass


def values(predicate):
    return list(predicate['value']) if predicate['op'] == 'in' else [predicate['value']]


def leaf(rule):
    """One old aggregate rule (JSON) → the SPADL rule JSON; raises Unsupported."""
    out, types, extra = [], None, None
    for p in rule.get('predicates', []):
        if p['field'] == 'event_type':
            olds = values(p)
            mapped = [EVENT_TYPES.get(kind, (None, None, f'Unknown event type {kind}.')) for kind in olds]
            if missing := next((m for m in mapped if m[0] is None), None):
                raise Unsupported(missing[2])
            extras = {repr(m[1]) for m in mapped}
            if set(olds) == {'shot', 'goal'}:
                chosen, extra_here = SHOTS, None
            elif len(extras) > 1 or (len(olds) > 1 and mapped[0][1] is not None):
                raise Unsupported('These event types have no single SPADL filter.')
            else:
                chosen, extra_here = sorted({t for m in mapped for t in m[0]}), mapped[0][1]
            types = chosen if types is None else sorted(set(types) & set(chosen))
            extra = extra_here or extra
        elif p['field'] == 'outcome':
            mapped = [OUTCOMES.get(v) for v in values(p)]
            if None in mapped or len({field for field, _ in mapped}) != 1:
                raise Unsupported('Card colours and mixed outcomes are outside SPADL.')
            field = mapped[0][0]
            out.append({'field': field, 'op': 'in', 'value': [value for _, value in mapped]})
            if field == 'shot_outcome' and types is None:
                types = SHOTS
        elif p['field'] == 'body_part':
            out.append({'field': 'bodypart', 'op': 'in', 'value': sorted({b for v in values(p) for b in BODY_PARTS[v]})})
        elif p['field'] in KEPT:
            out.append(p)
        else:
            raise Unsupported(f"Field {p['field']} has no SPADL equivalent.")
    if any(p['field'] == 'shot_outcome' for p in out):
        types = sorted(set(types or SHOTS) & set(SHOTS))
        extra = None if extra and extra['field'] == 'result' and extra['value'] == 'fail' else extra
    if types is not None:
        out.insert(0, {'field': 'action_type', 'op': 'in', 'value': types})
    if extra:
        out.append(extra)
    return {**{k: rule[k] for k in ('match_id', 'operation', 'sum_field', 'coverage') if k in rule}, 'predicates': out}


def convert(rule):
    """Old rule JSON (aggregate or formula) → SPADL Rule; raises Unsupported."""
    from backend.models.rules import Rule
    if rule.get('inputs'):
        return Rule.model_validate({'match_id': rule['match_id'], 'operation': rule['operation'],
                                    'inputs': [leaf(item) for item in rule['inputs']]})
    return Rule.model_validate(leaf(rule))


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS rule_vocabulary_map (
        old_field text NOT NULL, old_value text NOT NULL, spadl jsonb, supported boolean NOT NULL, note text NOT NULL,
        PRIMARY KEY (old_field, old_value))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS calculation_id_map (
        match_id text NOT NULL, old_id text NOT NULL, new_id text, reason text,
        PRIMARY KEY (match_id, old_id))''')
    rows = [('event_type', kind, Jsonb({'action_type': types, **({'and': extra} if extra else {})}) if types else None,
             types is not None, note) for kind, (types, extra, note) in EVENT_TYPES.items()]
    rows += [('outcome', old, Jsonb({field: value}), True, '') for old, (field, value) in OUTCOMES.items()]
    rows += [('outcome', colour, None, False, 'Cards are outside SPADL.') for colour in ('red', 'yellow', 'second_yellow')]
    rows += [('body_part', old, Jsonb({'bodypart': new}), True, '') for old, new in BODY_PARTS.items()]
    with conn.cursor() as cursor:
        cursor.executemany('INSERT INTO rule_vocabulary_map VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING', rows)
    for row in conn.execute('SELECT match_id, calculation_id, label, rule, result FROM match_calculations').fetchall():
        old = row['calculation_id']
        try:
            rule = convert(row['rule'])
        except (Unsupported, ValueError) as exc:
            reason = str(exc) if isinstance(exc, Unsupported) else 'This rule has no SPADL equivalent.'
            conn.execute('INSERT INTO calculation_id_map VALUES (%s,%s,NULL,%s) ON CONFLICT DO NOTHING',
                         (row['match_id'], old, reason))
            conn.execute("UPDATE question_offers SET document = document || jsonb_build_object('unsupported', %s::text) "
                         'WHERE calculation_id=%s', (reason, old))
            conn.execute('DELETE FROM match_calculations WHERE match_id=%s AND calculation_id=%s', (row['match_id'], old))
            continue
        new = rule.calculation_id
        conn.execute('INSERT INTO calculation_id_map VALUES (%s,%s,%s,NULL) ON CONFLICT DO NOTHING', (row['match_id'], old, new))
        conn.execute('DELETE FROM match_calculations WHERE match_id=%s AND calculation_id=%s', (row['match_id'], old))
        conn.execute('INSERT INTO match_calculations (match_id, calculation_id, label, rule, result) VALUES (%s,%s,%s,%s,%s) '
                     'ON CONFLICT DO NOTHING', (row['match_id'], new, row['label'], Jsonb(rule.model_dump(mode='json')),
                                                Jsonb({'calculation_id': new, 'value': 0.0,
                                                       'version': row['result'].get('version', 1)})))
        conn.execute("UPDATE question_offers SET calculation_id=%s, document = document || jsonb_build_object('rule', %s::jsonb) "
                     '- \'goal\' WHERE calculation_id=%s', (new, Jsonb(rule.model_dump(mode='json')), old))
    # Untracked offers in old chats: their rules no longer validate, so they can no longer be tracked.
    conn.execute("UPDATE question_offers SET document = document || jsonb_build_object('unsupported', "
                 "'Offered before statistics moved to SPADL; ask again to track it.') "
                 "WHERE calculation_id IS NULL AND document ? 'rule' AND document->'rule' @? "
                 "'$.** ? (@.field == \"event_type\" || @.field == \"outcome\" || @.field == \"body_part\")'")
