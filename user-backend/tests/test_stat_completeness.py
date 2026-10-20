"""Do not turn unknown attribution into an exact player total."""
import asyncio
from types import SimpleNamespace

from backend.models.events import Event
from backend.models.rules import Rule
from backend.services.question_tools import QuestionTools
from backend.services.rule_availability import incomplete_player_rule, observed_unattributed_events


def goal(**changes):
    return Event.model_validate({'event_id': 'goal', 'match_id': 'match', 'event_type': 'goal',
                                 'team_id': 'away', 'match_time_seconds': 600, **changes})


def player_rule(*predicates):
    return Rule.model_validate({'match_id': 'match', 'predicates': [
        {'field': 'event_type', 'op': 'in', 'value': ['shot', 'goal']},
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


def test_attribution_correction_or_retraction_restores_completeness():
    initial = goal()
    for correction in (goal(revision=2, player_id='striker'), goal(revision=2, deleted=True)):
        # Older late deliveries cannot undo the corrected attribution.
        assert not observed_unattributed_events([initial, correction, initial])
        assert not incomplete_player_rule(player_rule(), observed_unattributed_events([initial, correction]))


def test_custom_answer_refuses_partial_player_total_from_paginated_history():
    async def run():
        class Planner:
            async def plan(self, *args, **kwargs):
                return SimpleNamespace(status='ready', rule=player_rule(), goal=None)
        class History:
            async def events(self, snapshot, **filters):
                events = [goal(event_id='known', player_id='striker'), goal()]
                index = filters['offset']
                return {'complete': True, 'items': [events[index].model_dump()], 'has_more': index == 0}
        snapshot = SimpleNamespace(match_id='match', clock_seconds=600, period=1, id='snapshot', run_id='run')
        payload = SimpleNamespace(snapshot=snapshot, players=[], teams=[], data_reference={})
        tools = QuestionTools(payload, History(), None, Planner(), [], {}, [])
        result = await tools.prepare('How many shots has the striker taken?')
        assert result['status'] == 'unsupported'
        assert tools.offers == []
    asyncio.run(run())
