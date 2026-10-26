"""One comparison pin, live per-team values, and an independent Ask reset over real Postgres."""
from uuid import uuid4

from backend.agents.compiler import StructuredRuleCompiler
from backend.agents.models import Goal, GoalDecision
from backend.agents.workflow import RuleWorkflow
from harness import MATCH, Running
from support import ask, path, refresh, start


class TeamGoal:
    async def define(self, prompt, context):
        return GoalDecision(status='custom', goal=Goal(description='Headed shots for each team',
            action_types=('shot', 'shot_penalty', 'shot_freekick'), bodyparts=('head',)))


def test_one_comparison_pin_updates_both_teams_and_survives_restart(store):
    planner = RuleWorkflow(TeamGoal(), StructuredRuleCompiler(), source='fixture')
    with Running(store, planner=planner) as run:
        run.send(10)
        token = start(run.client)['session_token']
        reply = ask(run.client, token, 'Headed shots for each team')
        assert reply['status'] == 'answer', reply
        assert len(reply['offers']) == 1
        offer = reply['offers'][0]
        assert offer['kind'] == 'comparison' and len(offer['sides']) == 2
        response = run.client.post(path(token) + f'/offers/{offer["id"]}/track')
        assert response.status_code == 200, response.text
        pin = response.json()['calculation']['id']
        assert len(response.json()['snapshot']['cards']) == 5
        assert len([card for card in response.json()['snapshot']['cards'] if card.get('pinned')]) == 1
        run.send(35)
        refresh(run)
        card = run.client.get(path(token)).json()['snapshot']['cards'][-1]
        expected = {team['id']: sum(a.team_id == team['id'] and a.bodypart == 'head'
                    and a.action_type in ('shot', 'shot_penalty', 'shot_freekick') for a in run.match().actions)
                    for team in run.match().info['teams']}
        assert {side['team_id']: side['value'] for side in card['sides']} == expected
        assert sum(expected.values()) > 0
        upstream = run.upstream
    with Running(store, matches=(), upstream=upstream, planner=planner) as run:
        restored = run.client.get(path(token)).json()
        assert restored['snapshot']['cards'][-1]['sides'] == card['sides']
        assert run.client.delete(path(token) + f'/pins/{pin}').status_code == 200
        assert not any(c.get('pinned') for c in run.client.get(path(token)).json()['snapshot']['cards'])


def test_clear_ask_preserves_pins_follow_chat_and_other_viewers(store):
    with Running(store) as run:
        run.send(35)
        token = start(run.client)['session_token']
        other = run.client.post(f'/product/matches/{MATCH}/sessions', json={
            'profile_id': 'riverton-analytical', 'viewer_id': str(uuid4())}).json()['session_token']
        ask(run.client, other, 'what is offside')
        offer = ask(run.client, token, "Track Mbappe's headed shots")['offers'][0]
        assert run.client.post(path(token) + f'/offers/{offer["id"]}/track').status_code == 200
        ask(run.client, token, 'what is offside')
        repository = run.service.repository
        follow = repository.begin(token, uuid4(), 'Keep this follow conversation', channel='follow')
        repository.finish(token, follow['id'], {'text': 'Follow context', 'offers': []})
        response = run.client.delete(path(token) + '/messages')
        assert response.status_code == 200, response.text
        cleared = response.json()
        assert cleared['turns'] == [] and len(cleared['offers']) == 1
        assert cleared['snapshot']['cards'][-1]['pinned']
        assert cleared['follow_turns'][0]['prompt'] == 'Keep this follow conversation'
        assert len(run.client.get(path(other)).json()['turns']) == 1
        assert run.client.get(path(token)).json()['turns'] == []
        ask(run.client, token, 'what is offside')
        assert len(run.client.get(path(token)).json()['turns']) == 1
        pending = repository.begin(token, uuid4(), 'Pending')
        assert run.client.delete(path(token) + '/messages').status_code == 409
        repository.fail(token, pending['id'])


def test_etl_comparison_pin_stays_live_without_custom_calculations(store):
    from backend.models.questions import QuestionDraft

    class Agent:
        mode = 'fixture'
        async def answer(self, prompt, context, tools):
            return QuestionDraft(answer_kind='statistic', status='answer', standard_stat_id='all:shots',
                                 statistic_request=prompt, text='Shots')

    with Running(store, agent=Agent()) as run:
        run.send(10)
        token = start(run.client)['session_token']
        offer = ask(run.client, token, 'Shots for each team')['offers'][0]
        assert offer['kind'] == 'comparison'
        result = run.client.post(path(token) + f'/offers/{offer["id"]}/track')
        assert result.status_code == 200, result.text
        assert run.match().engine.count == 0
        run.send(35)
        refresh(run)
        card = run.client.get(path(token)).json()['snapshot']['cards'][-1]
        stats = run.app.state.product.projections[MATCH].shared['stats']
        assert {s['team_id']: s['value'] for s in card['sides']} == {
            row['team_id']: row['value'] for row in stats if row['id'].endswith(':shots') and row.get('team_id')}
