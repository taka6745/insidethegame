"""Do not turn unknown attribution into an exact player total."""
import asyncio
from types import SimpleNamespace

from backend.models.actions import SpadlAction
from backend.models.rules import Rule
from backend.services.question_tools import QuestionTools
from backend.services.rule_availability import incomplete_player_rule, observed_unattributed_events


def goal(**changes):
    return SpadlAction.model_validate({'match_id': 'match', 'action_id': 0, 'period': 1, 'match_time_seconds': 600,
                                       'team_id': 'away', 'action_type': 'shot', 'result': 'success', 'bodypart': 'foot',
                                       'start_x': 90.0, 'start_y': 34.0, 'end_x': 105.0, 'end_y': 34.0,
                                       'start_zone': 'opp_box', 'end_zone': 'opp_box', 'seq': 1, 'final_seq': 1, **changes})


def player_rule(*predicates):
    return Rule.model_validate({'match_id': 'match', 'predicates': [
        {'field': 'action_type', 'op': 'in', 'value': ['shot', 'shot_penalty', 'shot_freekick']},
        {'field': 'player_id', 'op': 'eq', 'value': 'striker'}, *predicates]})


def test_unknown_player_changes_completeness_only_after_observation():
    rule = player_rule()
    assert not incomplete_player_rule(rule, observed_unattributed_events([]))
    assert incomplete_player_rule(rule, observed_unattributed_events([goal()]))
    assert not incomplete_player_rule(Rule(match_id='match'), observed_unattributed_events([goal()]))


def test_unknown_player_respects_other_constraints():
    unknown = observed_unattributed_events([goal()])
    for predicate in ({'field': 'team_id', 'op': 'eq', 'value': 'home'},
                      {'field': 'match_time_seconds', 'op': 'lt', 'value': 600},
                      {'field': 'period', 'op': 'eq', 'value': 2}):
        assert not incomplete_player_rule(player_rule(predicate), unknown)


def test_custom_answer_refuses_partial_player_total():
    async def run():
        class Planner:
            async def plan(self, *args, **kwargs):
                return SimpleNamespace(status='ready', rule=player_rule(), goal=None)
        snapshot = SimpleNamespace(match_id='match', clock_seconds=600, period=1, id='snapshot', seq=1)
        actions = [goal(player_id='striker'), goal(action_id=1)]
        payload = SimpleNamespace(snapshot=snapshot, players=[], teams=[], data_reference={}, actions=actions)
        tools = QuestionTools(payload, None, None, Planner(), [], {}, [])
        result = await tools.prepare('How many shots has the striker taken?')
        assert result['status'] == 'unsupported'
        assert tools.offers == []
    asyncio.run(run())
