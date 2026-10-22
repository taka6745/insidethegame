"""Feed-aware recorded counts, including the reported United conversation."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from benchmarks.doubles.recording import FixtureEventSource
from backend.adapters.match_reference import data_reference
from backend.models.actions import SpadlAction
from backend.agents.compiler import StructuredRuleCompiler
from backend.agents.measurement_support import measurement_support, plain_measure
from backend.agents.models import Goal
from backend.agents.orchestrator import GoalAgent
from backend.agents.question import QuestionAgent
from backend.agents.question_intent import QuestionIntentRouter, routing_context
from backend.agents.workflow import RuleWorkflow
from backend.models.questions import QuestionDraft
from backend.services.question_answers import UNAVAILABLE, model_catalogue, resolve_answer, unavailable
from backend.services.rule_availability import supported_rule, unsupported_reason
from harness import MATCH, Running, Upstream, ask, session

INITIAL = "how many times has the ball touched forgeham's head"
FOLLOW_UP = 'any of them. anytime the ball touched someones head'
CAPABILITIES = {'supported_event_types': ['pass', 'shot', 'goal', 'clearance'],
                'body_parts': False, 'body_part_event_types': ['pass', 'shot', 'goal'],
                'shot_outcomes': True, 'coordinates': 'opta_0_100'}
PASS = ['pass', 'cross', 'throw_in', 'freekick_crossed', 'freekick_short', 'corner_crossed', 'corner_short', 'goalkick']
SHOTS = ['shot', 'shot_penalty', 'shot_freekick']


def test_contract_follows_feed_coverage_not_observed_events():
    reference = data_reference(CAPABILITIES)
    partial = measurement_support(reference)
    assert partial['declared'] and partial['contract_id'] == 'spadl-v1'
    assert partial['complete_bodypart_types'] == sorted(PASS + SHOTS)
    assert partial['recorded_bodyparts'] and partial['shot_outcomes'] and partial['locations']
    assert {'action_type', 'result', 'bodypart', 'start_zone', 'end_zone', 'end_x'} <= set(partial['filters'])
    assert any('Possession' in text for text in partial['unavailable'])  # Outside SPADL, named.
    assert measurement_support({}) == {'declared': False}
    assert measurement_support(data_reference(None)) == {'declared': False}
    routed = routing_context({'data_reference': reference, 'compact': {'text': 'secret recap'}})
    assert routed['measurement_support'] == partial
    assert 'secret recap' not in json.dumps(routed)


def action(**changes):
    base = {'match_id': 'match', 'action_id': 0, 'period': 1, 'match_time_seconds': 60, 'team_id': 'forgeham',
            'player_id': 'forgeham-1', 'action_type': 'clearance', 'result': 'success', 'bodypart': 'head',
            'bodypart_observed': True, 'start_x': 10.0, 'start_y': 30.0, 'end_x': 30.0, 'end_y': 30.0,
            'start_zone': 'own_box', 'end_zone': 'defensive_third', 'seq': 1, 'final_seq': 1}
    return SpadlAction(**base | changes)


def test_recorded_count_requires_declared_body_parts_and_counts_only_observed():
    goal = Goal(description='Recorded headers', bodyparts=['head'], coverage='recorded')
    rule = goal.target_rule('match')
    assert supported_rule(rule, CAPABILITIES)
    assert not supported_rule(rule, {})
    assert not supported_rule(rule, {**CAPABILITIES, 'body_part_event_types': []})
    # A complete header count needs body parts for every selected type.
    assert not supported_rule(rule.model_copy(update={'coverage': 'complete'}), CAPABILITIES)
    assert supported_rule(goal.model_copy(update={'coverage': 'complete', 'action_types': tuple(PASS)}).target_rule('match'),
                          CAPABILITIES)
    assert rule.calculation_id != rule.model_copy(update={'coverage': 'complete'}).calculation_id
    assert rule.matches(action()) and not rule.matches(action(bodypart_observed=False))
    assert not rule.matches(action(bodypart='foot_left'))
    # The mechanism works for any body part, not a header exception.
    assert supported_rule(goal.model_copy(update={'bodyparts': ('foot_left',)}).target_rule('match'), CAPABILITIES)
    with pytest.raises(ValidationError):
        Goal(description='Invalid escape hatch', coverage='recorded', operation='sum', sum_field='distance_metres',
             action_types=['pass'])
    # Reported: "Kai Ashworth's touches" came back recorded with no body part and failed validation
    # twice, so the viewer got "unsupported". A plain count of every action is a complete count.
    plain = Goal(description="Kai Ashworth's on-ball actions", coverage='recorded', player_ids=['riverton-1'])
    assert plain.coverage == 'complete' and supported_rule(plain.target_rule('match'), CAPABILITIES)


class CoverageRouterModel:
    async def complete(self, instructions, payload, **kwargs):
        support = payload['measurement_support']
        assert support['recorded_bodyparts'], support
        assert "headers" not in instructions.lower()
        assert payload['question'] in (INITIAL, FOLLOW_UP)
        if payload['question'] == FOLLOW_UP:
            assert payload['dialogue'][-1]['user'] == INITIAL
        return {'route': 'statistic'}


class RecordedContactsModel:
    async def complete(self, instructions, payload, **kwargs):
        # The SPADL metric mapping names bodyparts=[head] for headers; recorded coverage itself is generic.
        assert payload['measurement_support']['recorded_bodyparts']
        if payload['request'] == FOLLOW_UP:
            assert payload['context']['conversation'][0]['content'] == INITIAL
        return {'status': 'custom', 'goal': {'description': 'Forgeham United headers',
                'team_ids': ['forgeham'], 'bodyparts': ['head'], 'coverage': 'recorded'}}


def contact_source():
    """Independent golden actions: observed headers count, defaults and the other team do not."""
    spec = json.loads((Path(__file__).parents[2] / 'data-generation/recordings/riverton-forgeham-grf.json').read_text())
    def row(identifier, kind='pass', part='head', team='forgeham'):
        return {'eventId': identifier, 'matchId': spec['match_id'], 'revision': 1, 'typeName': kind,
                'teamId': team, 'playerId': team + '-1', 'periodId': 1, 'timeMin': 1, 'timeSec': 0, 'outcome': 'success',
                'qualifiers': [] if part is None else [{'type': 'bodyPart', 'value': part}]}
    rows = [row('a'), row('b', 'shot'), row('unknown', 'clearance', None), row('foot', part='foot'),
            row('other-team', team='riverton'), row('tackle', 'tackle', None), row('right', part='right_foot'),
            row('c'), row('foot-2', part='foot'), row('d', 'clearance'), row('riverton-2', team='riverton')]
    for i, event in enumerate(rows, 1):
        event['sequence'] = i
    spec.pop('playback', None)
    spec.update(events=rows, presets=[], capabilities=CAPABILITIES)
    return FixtureEventSource(content=json.dumps(spec).encode(), filename='recorded-contacts.json')


@pytest.mark.parametrize('legacy_clarification', [False, True])
def test_exact_united_conversation_answers_pins_and_updates_recorded_count(store, legacy_clarification):
    agent = QuestionAgent(SimpleNamespace(), router=QuestionIntentRouter(CoverageRouterModel()))
    upstream = Upstream()
    upstream.add(MATCH, contact_source())
    planner = RuleWorkflow(GoalAgent(RecordedContactsModel()), StructuredRuleCompiler())
    chat = f'/lab/matches/{MATCH}/chat'
    with Running(store, agent=agent, planner=planner, upstream=upstream) as run:
        sync = lambda: run.client.portal.call(run.service.match_data.capture, run.match())
        run.send(7)
        token = session(run.client)
        if legacy_clarification:
            turn = run.service.repository.begin(token, uuid4(), INITIAL)
            run.service.repository.finish(token, turn['id'], {
                'status': 'clarification', 'answer_kind': 'statistic', 'offers': [],
                'text': 'Do you mean all headed contacts (any touch with the head), headed passes, '
                        'or headed shots by Forgeham United?'})
        else:
            first = ask(run.client, token, INITIAL).json()
            assert first['status'] == 'answer', first
            assert first['offers'][0]['value'] == 2
        second = ask(run.client, token, FOLLOW_UP).json()
        assert second['status'] == 'answer', second
        assert second['text'] == 'Recorded Forgeham United headers: 2.'
        assert second['clarification'] is None
        assert run.match().engine.count == 0  # Offered, not auto-pinned.
        offer = second['offers'][0]
        tracked = run.client.post(f'{chat}/{token}/offers/{offer["id"]}/track')
        assert tracked.status_code == 200, tracked.text
        identifier = tracked.json()['calculation']['id']
        assert tracked.json()['calculation']['value'] == 2
        for expected in (3, 3, 4, 4):
            run.send(1)
            sync()
            assert run.match().engine.get(identifier).value == expected
        saved = run.client.get(f'{chat}/{token}').json()
        assert [turn['prompt'] for turn in saved['turns']] == [INITIAL, FOLLOW_UP]
        assert saved['offers'][-1]['calculation_id'] == identifier
    with Running(store, upstream=upstream, matches=()) as run:
        run.client.portal.call(run.service.match_data.capture, run.match())  # Actions are read again from ETL.
        assert run.match().engine.rule(identifier).coverage == 'recorded'
        assert run.match().engine.get(identifier).value == 4
        assert run.client.get(f'{chat}/{token}').json()['offers'][-1]['calculation_id'] == identifier


TEAMS = [{'id': 'riverton', 'name': 'Riverton Rovers'}, {'id': 'forgeham', 'name': 'Forgeham United'}]


def stat(identifier, label, team, value):
    return {'id': identifier, 'label': label, 'team_id': team, 'value': value, 'unit': '%',
            'available': True, 'complete': True}


# Shipped Riverton Rovers–United values: ETL possession is a share, not a count of events.
CATALOGUE = [stat('all:possession', 'Both teams possession', None, 100.0),
             stat('riverton:possession', 'Riverton Rovers possession', 'riverton', 53.2),
             stat('forgeham:possession', 'Forgeham United possession', 'forgeham', 46.8),
             stat('all:pass_accuracy', 'Both teams pass accuracy', None, 79.4),
             stat('riverton:pass_accuracy', 'Riverton Rovers pass accuracy', 'riverton', 81.0),
             stat('forgeham:pass_accuracy', 'Forgeham United pass accuracy', 'forgeham', 77.1)]


class PlainCountModel:
    def __init__(self, goal):
        self.goal = goal

    async def complete(self, instructions, payload, **kwargs):
        return {'status': 'custom', 'goal': self.goal}


@pytest.mark.parametrize('request_text, goal, status, standard_stat_id', [
    # Reported: the split compiled as a count of every Riverton Rovers/United event (11,388).
    ('What is the possession split?', {'description': 'Possession split', 'team_ids': ['riverton', 'forgeham']},
     'reuse', 'all:possession'),
    ('How much possession has Riverton Rovers had?', {'description': 'Riverton Rovers possession', 'team_ids': ['riverton']},
     'reuse', 'riverton:possession'),
    ("What is United's pass accuracy?", {'description': 'United passes', 'team_ids': ['forgeham'],
     'action_types': PASS, 'results': ['success']}, 'reuse', 'forgeham:pass_accuracy'),
    ('Possession split in the second half?', {'description': 'Possession split', 'period': 2}, 'unsupported', None),
    ("What percentage of Ashworth's passes were completed?", {'description': 'Ashworth completed passes',
     'player_ids': ['riverton-1'], 'action_types': PASS, 'results': ['success']}, 'unsupported', None),
    ('How many times did United lose possession?', {'description': 'United bad touches',
     'team_ids': ['forgeham'], 'action_types': ['bad_touch']}, 'ready', None),
    # Reported: declined as "a percentage needs two counts". A split of a count is per team.
    ('Shots split per team', {'description': 'Shots split per team', 'action_types': SHOTS}, 'ready', None),
])
def test_named_measure_is_never_a_plain_event_count(request_text, goal, status, standard_stat_id):
    context = {'match_id': 'm', 'teams': TEAMS, 'players': [{'id': 'riverton-1', 'name': 'Kai Ashworth'}],
               'standard_stats': CATALOGUE}
    outcome = asyncio.run(RuleWorkflow(GoalAgent(PlainCountModel(goal)), StructuredRuleCompiler())
                          .plan(request_text, context))
    assert (outcome.status, outcome.standard_stat_id) == (status, standard_stat_id)
    if status == 'unsupported':
        assert 'not a count of events' in outcome.message or 'two named counts' in outcome.message
    composite = Goal(description='Ashworth pass completion %', operation='percentage', inputs=[
        {'description': 'completed', 'action_types': PASS, 'results': ['success']},
        {'description': 'all', 'action_types': PASS}])
    assert not plain_measure('pass completion percentage', composite)


def tools_for(stats):
    return SimpleNamespace(stats=stats, offers=[], goal=None,
                           payload=SimpleNamespace(snapshot=SimpleNamespace(id='snapshot', match_id='match')))


def test_possession_split_answers_each_team_from_etl():
    tools = tools_for(CATALOGUE)
    draft = asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic', status='answer', text='?',
                                                     standard_stat_id='all:possession'), tools))
    assert draft.text == 'Riverton Rovers possession: 53.2%. Forgeham United possession: 46.8%.'
    assert [offer['standard_stat_id'] for offer in tools.offers] == ['riverton:possession', 'forgeham:possession']
    assert draft.evidence_ids == ['stat:riverton:possession', 'stat:forgeham:possession']
    # Overall pass accuracy is not the sum of team accuracies: one row.
    draft = asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic', status='answer', text='?',
                                                     standard_stat_id='all:pass_accuracy'), tools))
    assert draft.text == 'Both teams pass accuracy: 79.4%.'
    # Models see the split, not a bare 100% both-teams share; ids are unchanged for reuse.
    shown = {row['id']: row for row in model_catalogue(CATALOGUE)}
    assert shown['all:possession']['label'] == 'Possession split by team'
    assert shown['all:possession']['value'] == {'riverton': 53.2, 'forgeham': 46.8}
    assert shown['all:pass_accuracy'] == CATALOGUE[3]
    missing = tools_for([{**CATALOGUE[1], 'available': False, 'value': None}])
    draft = asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic', status='answer', text='?',
                                                     standard_stat_id='riverton:possession'), missing))
    assert draft.text == 'Sorry, I cannot answer that. Riverton Rovers possession is not available in this recording.'


def test_unsupported_answers_name_the_missing_channel():
    rule = lambda **goal: Goal(description='stat', **goal).target_rule('match')
    bare = {**CAPABILITIES, 'coordinates': None, 'shot_outcomes': False}
    assert unsupported_reason(rule(action_types=['clearance'], operation='sum', sum_field='distance_metres'),
                              bare) == 'This recording has no action locations.'
    assert unsupported_reason(rule(action_types=['pass'], end_zones=['opp_box']), bare) == 'This recording has no action locations.'
    assert unsupported_reason(rule(action_types=['shot'], shot_outcomes=['saved']), bare) == 'This recording has no shot outcomes.'
    assert unsupported_reason(rule(action_types=['clearance'], bodyparts=['head']), CAPABILITIES).startswith(
        'This recording classifies body parts only for corner crossed')
    assert unsupported_reason(rule(action_types=['pass'], bodyparts=['head']), CAPABILITIES) is None
    assert unsupported_reason(rule(action_types=['clearance'], operation='sum', sum_field='distance_metres'),
                              CAPABILITIES) is None
    assert unavailable('This recording has no tracking speed or distance data.').text == (
        'Sorry, I cannot answer that. This recording has no tracking speed or distance data.')
    # Model-written reasons cannot carry numbers; unknown reasons stay generic.
    for reason in (None, '', 'Ashworth ran 11 km.', 'x' * 241):
        assert unavailable(reason).text == UNAVAILABLE


def test_plain_saves_read_real_goalkeeper_saves():
    from backend.agents.measurement_support import measure_decision
    from backend.agents.models import GoalDecision
    context = {'standard_stats': [{'id': f'{s}:{k}'} for s in ('all', 'home') for k in ('saves', 'shots_saved')]}
    reuse = measure_decision('How many saves has each team made?',
                             GoalDecision(status='reuse', standard_stat_ids=['home:saves', 'all:saves']), context)
    assert reuse.standard_stat_ids == ['home:shots_saved', 'all:shots_saved'] and reuse.standard_stat_id == 'home:shots_saved'
    every = GoalDecision(status='reuse', standard_stat_id='all:saves')
    assert measure_decision('All save events, including blocks', every, context) is every
    custom = measure_decision('Bertolli saves', GoalDecision(status='custom', goal=Goal(
        description='Saves', action_types=['keeper_save'], player_ids=['p1'])), context)
    assert custom.goal.save_kinds == ('save',)


def test_standard_stat_route_reads_real_goalkeeper_saves():
    # The question agent's standard_stat route, not only the planner, maps plain 'saves' to shots_saved.
    stats = [{'id': f'all:{k}', 'label': label, 'value': value, 'available': True, 'complete': True}
             for k, label, value in (('saves', 'Saves', 9), ('shots_saved', 'Shots saved', 7))]
    def ask_for(prompt):
        tools = tools_for(stats)
        tools.original_prompt = prompt
        return asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic', status='answer', text='?',
                                                        standard_stat_id='all:saves'), tools))
    assert ask_for('How many saves so far?').evidence_ids == ['stat:all:shots_saved']
    assert ask_for('Every save event, including blocks').evidence_ids == ['stat:all:saves']
