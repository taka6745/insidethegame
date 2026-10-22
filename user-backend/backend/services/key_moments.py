"""Pivotal key moments for every viewer's feed: ETL's MA3 facts at the snapshot, labelled by configuration."""
import string

from backend.models.events import minute_label


class _Fields(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def label(template, **fields):
    return string.Formatter().vformat(template, (), _Fields(fields))


def score_text(template, teams, team_names, goals):
    home, away = (teams + [{'id': None}, {'id': None}])[:2]
    return label(template, home=team_names.get(home['id'], ''), away=team_names.get(away['id'], ''),
                 home_goals=goals.get(home['id'], 0), away_goals=goals.get(away['id'], 0))


def feed_moments(facts, config, teams, players, final_period=2):
    """facts: adapters/ma3.key_moment rows in match order. config: models/config.KeyMomentFeed. Period markers
    become kick_off, half_time, second_half and full_time (else period_start/period_end); a penalty is credited
    to the team that won it; a goal a VAR overturn names is marked `overturned`. {score} is the score after the
    moment (teams home first; an own goal counts for the opponent; a VAR overturn removes the goal it names)."""
    team_names = {t['id']: t.get('short_name') or t['name'] for t in teams}
    player_names = {p['id']: p['name'] for p in players}
    overturned = {f['related_event_id'] for f in facts if f['kind'] == 'var_overturn' and f['related_event_id']}
    goals, credited = {t['id']: 0 for t in teams}, {}
    seen, items = set(), []
    for fact in facts:
        kind, period = fact['kind'], fact['period']
        if kind in ('goal', 'own_goal'):
            team = fact['team_id'] if kind == 'goal' else next((t for t in goals if t != fact['team_id']), None)
            if team in goals:
                credited[str(fact['opta_event_id'])] = team
                goals[team] += 1
        elif kind == 'var_overturn' and str(fact['related_event_id']) in credited:
            team = credited.pop(str(fact['related_event_id']))
            goals[team] -= 1
        if kind in ('period_start', 'period_end'):
            if (kind, period) in seen:
                continue  # one row per team
            seen.add((kind, period))
            kind = {('period_start', 1): 'kick_off', ('period_start', 2): 'second_half', ('period_end', 1): 'half_time',
                    ('period_end', final_period): 'full_time'}.get((kind, period), kind)
        if kind not in config.kinds:
            continue
        team_id = fact['team_id']
        if kind == 'penalty':
            team_id = next((t for t in team_names if t != team_id), team_id)
        team, player = team_names.get(team_id, ''), player_names.get(fact['player_id'])
        score = score_text(config.score, teams, team_names, goals)
        subject = label(config.subject_with_player, player=player, team=team) if player else team
        items.append({'id': fact['id'], 'kind': kind, 'period': period, 'clock_seconds': fact['clock_seconds'],
                      'minute_label': minute_label(period, fact['clock_seconds']), 'event_seq': fact['event_seq'],
                      # A penalty's player is the one who conceded it, not of `team` (who won it): not on its card.
                      'team_id': team_id, 'player_id': fact['player_id'], 'team_name': team,
                      'player_name': None if kind == 'penalty' else player,
                      'score': score,  # after the moment; a clip's preview card shows it
                      'label': label(config.labels[kind], subject=subject, team=team, player=player or '',
                                     scorer=player or '', period=period, score=score).rstrip(' ·'),
                      'overturned': kind in ('goal', 'own_goal') and fact['opta_event_id'] is not None
                      and str(fact['opta_event_id']) in {str(i) for i in overturned}})
    return items
