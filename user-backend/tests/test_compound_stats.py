"""Multi-part, per-team and derived answers come from ETL rows and code, never one unsplit number."""
import asyncio
from types import SimpleNamespace

import pytest

from backend.agents.models import Goal, GoalDecision
from backend.models.actions import SpadlAction
from backend.models.questions import QuestionDraft
from backend.models.rules import Rule
from backend.services.question_answers import resolve_answer
from backend.services.question_tools import per_team

TEAMS = [{'id': 'riverton', 'name': 'Riverton Rovers'}, {'id': 'forgeham', 'name': 'Forgeham United'}]


def stats(**values):
    rows = []
    for key, value in values.items():
        team, kind = key.split('__')
        label = {'all': 'Both teams', 'riverton': 'Riverton Rovers', 'forgeham': 'Forgeham United'}[team]
        rows.append({'id': f'{team}:{kind}', 'label': f"{label} {kind.replace('_', ' ')}", 'value': value,
                     'team_id': None if team == 'all' else team, 'available': True, 'complete': True,
                     'unit': '%' if kind == 'possession' else ''})
    return rows


CARDS = [{'id': 'card:c1', 'seq': 10, 'colour': 'second_yellow', 'team_id': 'forgeham', 'player_id': 'forgeham-9',
          'match_time_seconds': 3078, 'period': 2, 'video_seconds': None},
         {'id': 'card:c2', 'seq': 9, 'colour': 'yellow', 'team_id': 'forgeham', 'player_id': 'forgeham-7',
          'match_time_seconds': 2700, 'period': 1, 'video_seconds': None}]


def tools(prompt, rows, result=None):
    async def cards(snapshot):
        return CARDS

    async def prepare_original():
        return result
    evidence = {}
    return SimpleNamespace(
        original_prompt=prompt, stats=rows, offers=[], goal=None, answer_text=None, evidence=evidence,
        prepared_results={}, prepare_original=prepare_original,
        payload=SimpleNamespace(snapshot=SimpleNamespace(id='s', match_id='m'),
                                players=[{'id': 'forgeham-9', 'name': 'Callum Brightwell'}]),
        match_data=SimpleNamespace(cards=cards),
        _event_reference=lambda row: evidence.setdefault(row['id'], {**row, 'evidence_id': row['id']}))


def answer(prompt, rows, result):
    toolkit = tools(prompt, rows, result)
    draft = QuestionDraft(answer_kind='statistic', status='answer', text='Checking.')
    reply = asyncio.run(resolve_answer(draft, toolkit))
    return reply, toolkit


ALL = dict(all__goals=1, riverton__goals=1, forgeham__goals=0, all__shots=10, riverton__shots=5, forgeham__shots=5,
           all__corners=3, riverton__corners=0, forgeham__corners=3, all__possession=100.0,
           riverton__possession=51.4, forgeham__possession=48.6, riverton__shots_on_target=2, all__cards=2, forgeham__cards=2)


def reuse(rows, *ids, formula=None):
    picked = [next(r for r in rows if r['id'] == i) for i in ids]
    return {'status': 'reuse', 'stat': picked[0], 'stats': picked, 'formula': formula}


def test_score_and_shots_per_team_are_split_and_scored():
    rows = stats(**ALL)
    reply, toolkit = answer('Score and shots per team?', rows, reuse(rows, 'all:goals', 'all:shots'))
    assert [o['standard_stat_id'] for o in toolkit.offers] == ['riverton:goals', 'forgeham:goals', 'riverton:shots', 'forgeham:shots']
    assert reply.text == 'Score: Riverton Rovers 1–0 Forgeham United. Riverton Rovers shots: 5. Forgeham United shots: 5.'


def test_each_team_splits_a_both_teams_row_but_a_plain_total_does_not():
    rows = stats(**ALL)
    _, toolkit = answer('Corners each team', rows, reuse(rows, 'all:corners'))
    assert [(o['standard_stat_id'], o['value']) for o in toolkit.offers] == [('riverton:corners', 0), ('forgeham:corners', 3)]
    _, toolkit = answer('How many corners in the match?', rows, reuse(rows, 'all:corners'))
    assert [o['standard_stat_id'] for o in toolkit.offers] == ['all:corners']


def test_score_and_possession_split_from_two_parts():
    rows = stats(**ALL)
    reply, toolkit = answer('HT score + possession split', rows, reuse(rows, 'all:goals', 'all:possession'))
    assert len(toolkit.offers) == 4
    assert reply.text == 'Score: Riverton Rovers 1–0 Forgeham United. Riverton Rovers possession: 51.4%. Forgeham United possession: 48.6%.'


def test_percentage_of_two_etl_rows_is_computed_not_refused():
    rows = stats(**{**ALL, 'riverton__shots': 4})
    reply, toolkit = answer('% of Riverton Rovers shots on target', rows,
                            reuse(rows, 'riverton:shots_on_target', 'riverton:shots', formula='percentage'))
    assert reply.status == 'answer'
    assert reply.text == 'Riverton Rovers shots on target as a share of Riverton Rovers shots: 50% (2 of 4).'
    assert [o['kind'] for o in toolkit.offers] == ['standard', 'standard']  # Each input stays trackable.


@pytest.mark.parametrize('ids', [('riverton:shots', 'riverton:shots_on_target'), ('riverton:shots_on_target', 'forgeham:shots')])
def test_percentage_needs_a_same_team_subset(ids):
    rows = stats(**ALL)
    reply, toolkit = answer('% on target', rows, reuse(rows, *ids, formula='percentage'))
    assert reply.status == 'unsupported' and not toolkit.offers


def test_who_was_sent_off_is_read_from_ma3_cards():
    rows = stats(**ALL)
    reply, _ = answer('United cards, who was sent off', rows, reuse(rows, 'forgeham:cards'))
    assert reply.text == 'Forgeham United cards: 2. Sent off: Callum Brightwell (second yellow, 52′).'
    assert 'card:c1' in reply.evidence_ids
    reply, _ = answer('Who was sent off?', rows, {'status': 'unsupported', 'message': 'No.'})
    assert reply.status == 'answer' and reply.text == 'Sent off: Callum Brightwell (second yellow, 52′).'


def test_reuse_decision_accepts_several_ids_and_formula_needs_two():
    decision = GoalDecision(status='reuse', standard_stat_ids=['a', 'b'])
    assert decision.standard_stat_id == 'a'
    assert GoalDecision(status='reuse', standard_stat_id='a').standard_stat_ids == ['a']
    with pytest.raises(ValueError):
        GoalDecision(status='reuse', standard_stat_ids=['a'], formula='percentage')
    with pytest.raises(ValueError):
        GoalDecision(status='custom', goal=Goal(description='x'), formula='ratio')


def test_custom_each_team_count_is_one_goal_per_team():
    goal = Goal(description='Corners for each team', action_types=('corner_crossed', 'corner_short'), period=1)
    split = per_team(goal, 'Corners each team in the first half', TEAMS)
    assert [(g.team_ids, g.description, g.period) for g in split] == [
        (('riverton',), 'Riverton Rovers: Corners', 1), (('forgeham',), 'Forgeham United: Corners', 1)]
    both = Goal(description='Shots for Riverton Rovers and Forgeham United', action_types=('shot', 'shot_penalty', 'shot_freekick'), team_ids=('riverton', 'forgeham'))
    assert len(per_team(both, 'Shots?', TEAMS)) == 2
    split = per_team(Goal(description='Shots split per team', action_types=('shot', 'shot_penalty', 'shot_freekick')), 'Shots split per team', TEAMS)
    assert [g.description for g in split] == ['Riverton Rovers: Shots', 'Forgeham United: Shots']
    assert per_team(Goal(description='All corners', action_types=('corner_crossed', 'corner_short')), 'How many corners?', TEAMS) is None


def test_custom_saves_count_every_keeper_save_as_the_etl_saves_stat():
    def act(identifier, kind):
        return SpadlAction(match_id='m', action_id=identifier, action_type=kind, result='success', bodypart='other',
                           team_id='t', player_id='k', period=1, match_time_seconds=1, start_x=5.0, start_y=34.0,
                           end_x=5.0, end_y=34.0, start_zone='own_box', end_zone='own_box', seq=1, final_seq=1)
    rule = Goal(description='Keeper saves', action_types=('keeper_save',), player_ids=('k',)).target_rule('m')
    actions = [act(0, 'keeper_save'), act(1, 'keeper_save'), act(2, 'keeper_claim')]
    assert sum(rule.contribution(a) for a in actions) == 2
    everything = Rule(match_id='m', predicates=[{'field': 'player_id', 'op': 'eq', 'value': 'k'}])
    assert sum(everything.contribution(a) for a in actions) == 3


def test_who_was_sent_off_skips_model_prose():
    from backend.agents.question import EXPLAIN, QuestionAgent
    from backend.agents.question_intent import QuestionIntent

    class Router:
        async def route(self, *args):
            return QuestionIntent(route='match')
    agent = QuestionAgent(settings=object(), router=Router(), replay=object())
    draft = asyncio.run(agent.answer('United cards, who was sent off', {}, SimpleNamespace()))
    assert draft.answer_kind == 'statistic'
    assert EXPLAIN.search('Why was Brightwell sent off?')  # Explanations stay with the match answer.


def test_evidence_labels_and_prose_share_one_minute_rule():
    # Reported: a second yellow at 51:18 was cited as 51′ while the answer said 52′.
    from backend.models.events import minute_label
    from backend.services.question_tools import QuestionTools
    assert [minute_label(2, 3078), minute_label(1, 2730), minute_label(2, 5400), minute_label(1, 0)] == \
        ['52′', '45+1′', '90+1′', '1′']
    recap = {'id': 'recap:a', 'start_seconds': 4380, 'end_seconds': 4440}
    toolkit = QuestionTools(None, None, None, None, [], {'blocks': [recap, {**recap, 'id': 'recap:b', 'label': '74′'}],
                                                        'key_events': CARDS}, [])
    assert toolkit.evidence['card:c1']['label'] == '52′ second yellow card'
    assert toolkit._event_reference(CARDS[0])['minute'] == '52′'  # What the model copies into prose.
    assert [toolkit.evidence[i]['label'] for i in ('recap:a', 'recap:b')] == ['74′ recap', '74′ recap']
    reply, _ = answer('United cards, who was sent off', stats(**ALL), reuse(stats(**ALL), 'forgeham:cards'))
    assert 'Callum Brightwell (second yellow, 52′)' in reply.text
