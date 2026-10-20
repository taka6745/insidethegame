"""Feed-aware recorded counts, including the reported United conversation."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.adapters.replay_source import FixtureEventSource
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
from test_questions import ask, build, session

INITIAL = "how many times has the ball touched man utd's head"
FOLLOW_UP = 'any of them. anytime the ball touched someones head'
CAPABILITIES = {'supported_event_types': ['pass', 'shot', 'goal', 'touch'],
                'body_parts': False, 'body_part_event_types': ['pass', 'shot', 'goal'],
                'distance_event_types': ['pass'], 'shot_outcomes': True,
                'recorded_body_part_event_groups': [['touch']]}


def test_contract_follows_feed_coverage_not_observed_events():
    reference = {'contract_id': 'partial', 'capabilities': CAPABILITIES,
                 'events': {'touch': 'Contacts overlap passing actions.'}}
    partial = measurement_support(reference)
    assert partial['recorded_body_part_event_groups'] == [['touch']]
    assert not partial['all_event_body_parts']
    assert partial['distance_event_types'] == ['pass']
    assert partial['event_meanings']['touch'] == 'Contacts overlap passing actions.'
    assert measurement_support({}) == {'declared': False}
    assert measurement_support({**reference, 'unavailable': ['No tracking speed.']})['unavailable'] == ['No tracking speed.']
    routed = routing_context({'data_reference': reference, 'compact': {'text': 'secret recap'}})
    assert routed['measurement_support'] == partial
    assert 'secret recap' not in json.dumps(routed)


def test_recorded_count_requires_declared_nonoverlapping_group():
    goal = Goal(description='Recorded contacts', event_types=['touch'], body_part='head', coverage='recorded')
    rule = goal.target_rule('match')
    assert supported_rule(rule, CAPABILITIES)
    assert not supported_rule(rule, {})
    assert not supported_rule(rule.model_copy(update={'coverage': 'complete'}), CAPABILITIES)
    assert rule.calculation_id != rule.model_copy(update={'coverage': 'complete'}).calculation_id
    for categories in ([], ['touch', 'shot'], ['foul']):
        assert not supported_rule(goal.model_copy(update={'event_types': categories}).target_rule('match'), CAPABILITIES)
    # A different feed can declare disjoint action records without changing prompts or the engine.
    disjoint = {**CAPABILITIES, 'recorded_body_part_event_groups': [['pass', 'shot', 'goal']]}
    actions = goal.model_copy(update={'event_types': ['pass', 'shot', 'goal']}).target_rule('match')
    assert supported_rule(actions, disjoint)
    assert not supported_rule(rule, disjoint)
    # The mechanism also works for another qualifier value, not a header exception.
    assert supported_rule(goal.model_copy(update={'body_part': 'left_foot'}).target_rule('match'), CAPABILITIES)
    with pytest.raises(ValidationError):
        Goal(description='Invalid escape hatch', coverage='recorded', event_types=['foul'])


class CoverageRouterModel:
    async def complete(self, instructions, payload, **kwargs):
        support = payload['measurement_support']
        assert support['recorded_body_part_event_groups'] == [['touch']]
        assert "headers" not in instructions.lower()
        assert payload['question'] in (INITIAL, FOLLOW_UP)
        if payload['question'] == FOLLOW_UP:
            assert payload['dialogue'][-1]['user'] == INITIAL
        return {'route': 'statistic'}


class RecordedContactsModel:
    async def complete(self, instructions, payload, **kwargs):
        assert payload['measurement_support']['recorded_body_part_event_groups'] == [['touch']]
        assert "headers" not in instructions.lower()
        if payload['request'] == FOLLOW_UP:
            assert payload['context']['conversation'][0]['content'] == INITIAL
        return {'status': 'custom', 'goal': {'description': 'Manchester United headers',
                'team_ids': ['manutd'], 'event_types': ['touch'], 'body_part': 'head', 'coverage': 'recorded'}}


def contact_source():
    """Independent golden events: two actions with overlapping records, then corrections."""
    spec = json.loads((Path(__file__).parents[2] / 'data-generation/recordings/chelsea-united-grf.json').read_text())
    def row(identifier, kind='touch', part='head', team='manutd', revision=1, deleted=False):
        return {'eventId': identifier, 'matchId': spec['match_id'], 'revision': revision, 'typeName': kind,
                'teamId': team, 'playerId': team + '-1', 'periodId': 1, 'timeMin': 1, 'timeSec': 0,
                'qualifiers': [] if part is None else [{'type': 'bodyPart', 'value': part}], 'deleted': deleted}
    rows = [row('a'), row('pass-a', 'pass'), row('b'), row('shot-b', 'shot'),
            row('unknown', part=None), row('foot', part='foot'), row('other-team', team='chelsea'),
            row('c'), row('b', part='foot', revision=2), row('c'), row('a', revision=2, deleted=True)]
    for i, event in enumerate(rows, 1):
        event['sequence'] = i
    spec.pop('playback', None)
    spec.update(events=rows, presets=[], capabilities=CAPABILITIES)
    return FixtureEventSource(content=json.dumps(spec).encode(), filename='recorded-contacts.json')


@pytest.mark.parametrize('legacy_clarification', [False, True])
def test_exact_united_conversation_answers_pins_and_updates_recorded_count(store, legacy_clarification):
    agent = QuestionAgent(SimpleNamespace(), router=QuestionIntentRouter(CoverageRouterModel()))
    lab, service, _, app = build(store, agent)
    lab.source = contact_source()
    service.planner = RuleWorkflow(GoalAgent(RecordedContactsModel()), StructuredRuleCompiler())
    with TestClient(app) as client:
        for _ in range(7):
            client.portal.call(lab.advance)
        token = session(client)
        if legacy_clarification:
            turn = service.repository.begin(token, uuid4(), INITIAL)
            service.repository.finish(token, turn['id'], {
                'status': 'clarification', 'answer_kind': 'statistic', 'offers': [],
                'text': 'Do you mean all headed contacts (any touch with the head), headed passes, '
                        'or headed shots by Manchester United?'})
        else:
            first = ask(client, token, INITIAL).json()
            assert first['status'] == 'answer', first
            assert first['offers'][0]['value'] == 2
        second = ask(client, token, FOLLOW_UP).json()
        assert second['status'] == 'answer', second
        assert second['text'] == 'Recorded Manchester United headers: 2.'
        assert second['clarification'] is None
        assert lab.engine.count == 0  # Offered, not auto-pinned.
        offer = second['offers'][0]
        tracked = client.post(f'/lab/chat/{token}/offers/{offer["id"]}/track')
        assert tracked.status_code == 200, tracked.text
        identifier = tracked.json()['calculation']['id']
        assert tracked.json()['calculation']['value'] == 2
        for expected in (3, 2, 2, 1):
            client.portal.call(lab.advance)
            assert lab.engine.get(identifier).value == expected
        saved = client.get(f'/lab/chat/{token}').json()
        assert [turn['prompt'] for turn in saved['turns']] == [INITIAL, FOLLOW_UP]
        assert saved['offers'][-1]['calculation_id'] == identifier
    restored_lab, _, _, restored_app = build(store)
    restored_lab.source = contact_source()
    with TestClient(restored_app) as client:
        assert restored_lab.engine.rule(identifier).coverage == 'recorded'
        assert restored_lab.engine.get(identifier).value == 1
        assert client.get(f'/lab/chat/{token}').json()['offers'][-1]['calculation_id'] == identifier


TEAMS = [{'id': 'chelsea', 'name': 'Chelsea'}, {'id': 'manutd', 'name': 'Manchester United'}]


def stat(identifier, label, team, value):
    return {'id': identifier, 'label': label, 'team_id': team, 'value': value, 'unit': '%',
            'available': True, 'complete': True}


# Shipped Chelsea–United values: ETL possession is a share, not a count of events.
CATALOGUE = [stat('all:possession', 'Both teams possession', None, 100.0),
             stat('chelsea:possession', 'Chelsea possession', 'chelsea', 53.2),
             stat('manutd:possession', 'Manchester United possession', 'manutd', 46.8),
             stat('all:pass_accuracy', 'Both teams pass accuracy', None, 79.4),
             stat('chelsea:pass_accuracy', 'Chelsea pass accuracy', 'chelsea', 81.0),
             stat('manutd:pass_accuracy', 'Manchester United pass accuracy', 'manutd', 77.1)]


class PlainCountModel:
    def __init__(self, goal):
        self.goal = goal

    async def complete(self, instructions, payload, **kwargs):
        return {'status': 'custom', 'goal': self.goal}


@pytest.mark.parametrize('request_text, goal, status, standard_stat_id', [
    # Reported: the split compiled as a count of every Chelsea/United event (11,388).
    ('What is the possession split?', {'description': 'Possession split', 'team_ids': ['chelsea', 'manutd']},
     'reuse', 'all:possession'),
    ('How much possession has Chelsea had?', {'description': 'Chelsea possession', 'team_ids': ['chelsea']},
     'reuse', 'chelsea:possession'),
    ("What is United's pass accuracy?", {'description': 'United passes', 'team_ids': ['manutd'],
     'event_types': ['pass'], 'outcome': 'success'}, 'reuse', 'manutd:pass_accuracy'),
    ('Possession split in the second half?', {'description': 'Possession split', 'period': 2}, 'unsupported', None),
    ("What percentage of Palmer's passes were completed?", {'description': 'Palmer completed passes',
     'player_ids': ['chelsea-1'], 'event_types': ['pass'], 'outcome': 'success'}, 'unsupported', None),
    ('How many times did United lose possession?', {'description': 'United dispossessed',
     'team_ids': ['manutd'], 'event_types': ['dispossessed']}, 'ready', None),
])
def test_named_measure_is_never_a_plain_event_count(request_text, goal, status, standard_stat_id):
    context = {'match_id': 'm', 'teams': TEAMS, 'players': [{'id': 'chelsea-1', 'name': 'Cole Palmer'}],
               'standard_stats': CATALOGUE}
    outcome = asyncio.run(RuleWorkflow(GoalAgent(PlainCountModel(goal)), StructuredRuleCompiler())
                          .plan(request_text, context))
    assert (outcome.status, outcome.standard_stat_id) == (status, standard_stat_id)
    if status == 'unsupported':
        assert 'not a count of events' in outcome.message or 'two named counts' in outcome.message
    composite = Goal(description='Palmer pass completion %', operation='percentage', inputs=[
        {'description': 'completed', 'event_types': ['pass'], 'outcome': 'success'},
        {'description': 'resolved', 'event_types': ['pass'], 'outcomes': ['success', 'failure']}])
    assert not plain_measure('pass completion percentage', composite)


def tools_for(stats):
    return SimpleNamespace(stats=stats, offers=[], goal=None,
                           payload=SimpleNamespace(snapshot=SimpleNamespace(id='snapshot', run_id='run')))


def test_possession_split_answers_each_team_from_etl():
    tools = tools_for(CATALOGUE)
    draft = asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic', status='answer', text='?',
                                                     standard_stat_id='all:possession'), tools))
    assert draft.text == 'Chelsea possession: 53.2%. Manchester United possession: 46.8%.'
    assert [offer['standard_stat_id'] for offer in tools.offers] == ['chelsea:possession', 'manutd:possession']
    assert draft.evidence_ids == ['stat:chelsea:possession', 'stat:manutd:possession']
    # Overall pass accuracy is not the sum of team accuracies: one row.
    draft = asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic', status='answer', text='?',
                                                     standard_stat_id='all:pass_accuracy'), tools))
    assert draft.text == 'Both teams pass accuracy: 79.4%.'
    # Models see the split, not a bare 100% both-teams share; ids are unchanged for reuse.
    shown = {row['id']: row for row in model_catalogue(CATALOGUE)}
    assert shown['all:possession']['label'] == 'Possession split by team'
    assert shown['all:possession']['value'] == {'chelsea': 53.2, 'manutd': 46.8}
    assert shown['all:pass_accuracy'] == CATALOGUE[3]
    missing = tools_for([{**CATALOGUE[1], 'available': False, 'value': None}])
    draft = asyncio.run(resolve_answer(QuestionDraft(answer_kind='statistic', status='answer', text='?',
                                                     standard_stat_id='chelsea:possession'), missing))
    assert draft.text == 'Sorry, I cannot answer that. Chelsea possession is not available in this recording.'


def test_unsupported_answers_name_the_missing_channel():
    rule = lambda **goal: Goal(description='stat', **goal).target_rule('match')
    assert unsupported_reason(rule(event_types=['foul']), CAPABILITIES) == 'This recording does not capture foul events.'
    assert unsupported_reason(rule(event_types=['shot'], operation='sum', sum_field='distance_metres'),
                              CAPABILITIES) == 'This recording has distance data only for pass events.'
    assert unsupported_reason(rule(event_types=['touch'], body_part='head'), CAPABILITIES) == (
        'This recording has body-part data only for goal, pass, shot events.')
    assert unsupported_reason(rule(event_types=['pass'], body_part='head'), CAPABILITIES) is None
    assert unavailable('This recording has no tracking speed or distance data.').text == (
        'Sorry, I cannot answer that. This recording has no tracking speed or distance data.')
    # Model-written reasons cannot carry numbers; unknown reasons stay generic.
    for reason in (None, '', 'Palmer ran 11 km.', 'x' * 241):
        assert unavailable(reason).text == UNAVAILABLE
