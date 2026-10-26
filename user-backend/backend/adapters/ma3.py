"""Opta-style (MA1/MA3) names from ETL GraphQL → this service's canonical names.

Only this module knows the feed's camelCase keys; services see `supported_event_types`,
`team_id`, `short_name`, … (the names the rule engine and agents already use)."""
import json
import re

# MA1 capability keys whose canonical name is not the plain snake_case form.
RENAMED = {'eventTypes': 'supported_event_types'}
STATUSES = ('scheduled', 'live', 'finished')


def snake(name):
    return re.sub(r'(?<!^)([A-Z])', r'_\1', name).lower()


def json_value(value, default):
    if value in (None, ''):
        return default
    return json.loads(value) if isinstance(value, str) else value


def capabilities(raw):
    """MA1 `capabilities` (JSON text or object) → snake_case keys; None when not declared."""
    value = json_value(raw, None)
    if not value:
        return None
    if not isinstance(value, dict):
        raise ValueError('MA1 capabilities must be an object')
    return {RENAMED.get(key, snake(key)): item for key, item in value.items()}


def team(row):
    return {'id': row['contestantId'], 'name': row['name'], 'position': row['position'],
            'short_name': row.get('shortName') or row['name'], 'code': row.get('code'),
            'known_names': json_value(row.get('knownNames'), []),
            'branding': {'primary_colour': row.get('primaryColour'), 'secondary_colour': row.get('secondaryColour'),
                         'crest_asset_id': row.get('crestAssetId')}}


def player(row):
    return {'id': row['playerId'], 'name': row['name'], 'team_id': row['contestantId'],
            'shirt_number': row.get('shirtNumber'), 'position': row.get('position'), 'starter': row.get('starter')}


def match(row):
    """One DAB `matches` item → match info (teams home first, players, canonical capabilities)."""
    teams = sorted((team(item) for item in (row.get('teams') or {}).get('items', [])),
                   key=lambda item: item['position'] != 'home')
    if row.get('status') not in STATUSES:
        raise ValueError('Unknown match status')
    return {'match_id': row['matchId'], 'fixture': row['fixture'], 'source_match_id': row.get('sourceMatchId'),
            'status': row['status'], 'scheduled_kickoff': row.get('scheduledKickoff'),
            'description': row.get('description'), 'synthetic': bool(row.get('synthetic', True)),
            'capabilities': capabilities(row.get('capabilities')), 'teams': teams,
            'players': [player(item) for item in (row.get('players') or {}).get('items', [])]}


def stat(row):
    """One `executeStatsAtSeq` row → the stat row cards, questions and pins use. An unavailable row
    (a retired kind, or a channel this feed lacks) carries ETL's definition as its reason."""
    reason = None if row['available'] else (row.get('definition') or 'Not available in this recording.')
    return {'id': row['statId'], 'label': row['label'], 'value': row['value'], 'unavailable_reason': reason,
            'available': bool(row['available']), 'complete': bool(row['complete']),
            'team_id': row.get('contestantId'), 'unit': row.get('unit') or '',
            'definition': row.get('definition') or '', 'action_types': json_value(row.get('eventTypes'), [])}


CARD, GOAL, VAR = 17, 16, 900  # Opta types (900: VAR decision, ETL's synthetic extension)
OWN_GOAL, VAR_OUTCOME = 28, 901
CARD_COLOURS = {31: 'yellow', 32: 'second_yellow', 33: 'red'}  # Opta card qualifiers


def card(row):
    """One MA3 card row (DAB rawEvents, Opta type 17) → {id, seq, colour, team_id, player_id, ...}."""
    payload = json_value(row.get('payload'), {})
    qualifiers = {int(q['qualifierId']) for q in payload.get('qualifier') or []}
    colour = next((name for q, name in CARD_COLOURS.items() if q in qualifiers), 'yellow')
    return {'id': f"card:{row['id']}", 'seq': payload.get('eventSeq'), 'colour': colour,
            'team_id': row.get('contestantId'), 'player_id': row.get('playerId'), 'period': row['periodId'],
            'match_time_seconds': row['timeMin'] * 60 + row['timeSec'], 'video_seconds': payload.get('videoSeconds')}


def score(rows, teams):
    """Goals per contestant from MA3 goal and VAR rows already bounded by a snapshot (keyEvents' rules): an own
    goal counts for the opponent and a VAR overturn removes the goal it names."""
    goals = dict.fromkeys(teams, 0)
    for row in rows:
        payload = json_value(row.get('payload'), {})
        qualifiers = {int(q['qualifierId']): q.get('value') for q in payload.get('qualifier') or []}
        team = row['contestantId']
        if OWN_GOAL in qualifiers:
            team = next((t for t in teams if t != team), team)
        if row['typeId'] == GOAL:
            goals[team] = goals.get(team, 0) + 1
        elif row['typeId'] == VAR and qualifiers.get(VAR_OUTCOME) == 'goal-overturned':
            goals[team] = goals.get(team, 0) - 1
    return goals


# Pivotal key moments (local/README.md Contracts §8): Opta types the feed shows everyone. 4 / 13–15 matter only with
# qualifier 9 (penalty); 30 / 32 are period end / start (one row per team).
FOUL, MISS, POST, ATTEMPT_SAVED, PERIOD_END, PERIOD_START = 4, 13, 14, 15, 30, 32
PENALTY, RELATED = 9, 55
KEY_MOMENT_TYPES = (GOAL, CARD, VAR, FOUL, MISS, POST, ATTEMPT_SAVED, PERIOD_END, PERIOD_START)


def key_moment(row):
    """One MA3 row (DAB rawEvents) → a key-moment fact, or None. `kind`: goal, own_goal, red_card, second_yellow,
    penalty (awarded; `team_id` is the team that conceded it), penalty_missed, var_overturn, period_start, period_end.
    Rules follow ETL's keyEvents (etl/README.md Contracts, key event types)."""
    payload = json_value(row.get('payload'), {})
    qualifiers = {int(q['qualifierId']): q.get('value') for q in payload.get('qualifier') or []}
    kind, type_id = None, row['typeId']
    if type_id == GOAL:
        kind = 'own_goal' if OWN_GOAL in qualifiers else 'goal'
    elif type_id == CARD:
        kind = 'second_yellow' if 32 in qualifiers else 'red_card' if 33 in qualifiers else None
    elif type_id == VAR and str(qualifiers.get(VAR_OUTCOME, '')).endswith('overturned'):
        kind = 'var_overturn'
    elif type_id == FOUL and PENALTY in qualifiers and payload.get('outcome') == 0:
        kind = 'penalty'
    elif type_id in (MISS, POST, ATTEMPT_SAVED) and PENALTY in qualifiers:
        kind = 'penalty_missed'
    elif type_id in (PERIOD_START, PERIOD_END):
        kind = 'period_start' if type_id == PERIOD_START else 'period_end'
    if kind is None:
        return None
    seconds = row['timeMin'] * 60 + row['timeSec']
    return {'id': f"km:{row['id']}", 'kind': kind, 'opta_event_id': payload.get('eventId'),
            'related_event_id': qualifiers.get(RELATED), 'penalty': PENALTY in qualifiers,
            'team_id': None if kind.startswith('period') else row.get('contestantId'),
            'player_id': row.get('playerId'), 'period': row['periodId'], 'clock_seconds': seconds,
            'event_seq': payload.get('eventSeq', row.get('eventSeq')), 'video_seconds': payload.get('videoSeconds')}
