"""Several live matches at once: isolation, sessions per (profile, match), restart recovery,
no future data, per-match purge with tombstones, and no recording access from the runtime."""
import ast
import json
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from backend.adapters import etl_dab
from backend.adapters.match_stream import handle_match_message
from backend.models.questions import QuestionDraft
from backend.models.rules import Rule
from backend.services.filter_engine import FilterEngine
from benchmarks.doubles.recording import FixtureEventSource
from harness import MATCH, Running, Upstream, ask as lab_ask, session, timed
from test_product import OTHER, ask, deliver, narrative, path, refresh, start, until

BACKEND = Path(__file__).resolve().parents[1] / 'backend'


def other_source():
    """A second fixture with its own clubs and players, so any cross-match leak is visible."""
    data = json.loads(FixtureEventSource().content)
    names = {'chelsea': ('north', 'North FC'), 'madrid': ('south', 'South United')}
    for team in data['teams']:
        team['id'], team['name'] = names[team['id']]
    players = {p['id']: f'n-{p["id"]}' for p in data['players']}
    for index, player in enumerate(data['players']):
        player['id'], player['team_id'] = players[player['id']], names[player['team_id']][0]
        player['name'] = f'Player {index}'
    for event in data['events']:
        event['teamId'] = names.get(event.get('teamId'), (event.get('teamId'),))[0]
        event['playerId'] = players.get(event.get('playerId'), event.get('playerId'))
        event['eventId'] = 'n-' + event['eventId']
    data['presets'] = []
    return FixtureEventSource(content=json.dumps(data).encode())


def two_matches():
    upstream = Upstream()
    upstream.add(MATCH, timed())
    upstream.add(OTHER, timed(other_source()))
    return upstream


class Recorder:
    """Records the context of every question and answers with a replay of every shot."""
    mode = 'fixture'

    def __init__(self):
        self.contexts, self.found = [], []

    async def answer(self, prompt, context, tools):
        # The live-match list (names and minute only, PLAN.md §10.2 D5) is the one deliberate cross-match field.
        self.contexts.append(json.dumps({k: v for k, v in context.items() if k != 'live_matches'}))
        self.live = context.get('live_matches')
        found = await tools.replay.find_events(action_types=['shot', 'shot_penalty', 'shot_freekick'])
        self.found.append(found['listed'])
        items = [{'source_id': row['id'], 'kind': 'event', 'caption': 'Shot'} for row in found['listed']]
        return QuestionDraft(answer_kind='replay', status='answer', text='Shots.', replay_items=items)


def test_two_matches_never_cite_each_other(store):
    agent = Recorder()
    with Running(store, agent=agent, upstream=two_matches(), matches=(MATCH, OTHER)) as run:
        run.send(30, MATCH)
        run.send(12, OTHER)
        deliver(run, narrative(MATCH, event_seq=30, text='Chelsea story.'))
        deliver(run, narrative(OTHER, event_seq=12, text='North story.'))
        for match_id in (MATCH, OTHER):
            refresh(run, match_id)
        home, away = start(run.client), start(run.client, OTHER)
        cards = {c['id'].split(':')[0] for c in home['snapshot']['cards']}
        assert cards == {'chelsea'} and {c['id'].split(':')[0] for c in away['snapshot']['cards']} == {'north'}
        assert [n['text'] for n in home['snapshot']['narratives']] == ['Chelsea story.']
        assert [n['text'] for n in away['snapshot']['narratives']] == ['North story.']
        assert all(e['team_id'] in ('chelsea', 'madrid', None) for e in home['snapshot']['events'])
        assert all(e['team_id'] in ('north', 'south', None) for e in away['snapshot']['events'])
        first = ask(run.client, home['session_token'], 'show the shots')
        second = ask(run.client, away['session_token'], 'show the shots', OTHER)
        assert first['snapshot']['id'] == f'{MATCH}:30' and second['snapshot']['id'] == f'{OTHER}:12'
        assert first['replay']['clips'] is not None and second['replay']['items']
        assert agent.found[0] and all(row['team'] in ('Chelsea', 'Madrid') for row in agent.found[0])
        assert agent.found[1] and all(row['team'] in ('North FC', 'South United') for row in agent.found[1])
        assert 'North' not in agent.contexts[0] and 'South' not in agent.contexts[0]
        assert 'Chelsea' not in agent.contexts[1] and 'Mbapp' not in agent.contexts[1]
        # Custom stats are per match: a rule for one match is refused on the other.
        rule = {'match_id': OTHER, 'operation': 'count', 'predicates': []}
        assert run.client.post(f'/lab/matches/{MATCH}/calculations', json={'rule': rule}).status_code == 422


def test_one_profile_in_two_tabs_on_two_matches(store):
    with Running(store, upstream=two_matches(), matches=(MATCH, OTHER)) as run:
        run.send(3, MATCH)
        run.send(3, OTHER)
        a, b = start(run.client), start(run.client, OTHER)
        assert a['profile_id'] == b['profile_id'] and a['session_token'] != b['session_token']
        with run.client.websocket_connect(path(a['session_token']) + '/live') as one, \
                run.client.websocket_connect(path(b['session_token'], OTHER) + '/live') as two:
            assert one.receive_json()['match']['id'] == MATCH and two.receive_json()['match']['id'] == OTHER
            run.send(1, MATCH)
            assert until(one, lambda m: m['match']['seq'] == 4)['match']['id'] == MATCH
            run.send(1, OTHER)
            assert until(two, lambda m: m['match']['seq'] == 4)['match']['id'] == OTHER
            assert ask(run.client, a['session_token'], 'what is offside')['status'] == 'answer'
            assert ask(run.client, b['session_token'], 'what is offside', OTHER)['status'] == 'answer'
        # A token belongs to its match.
        assert run.client.get(path(a['session_token'], OTHER)).status_code == 404


def test_restart_rebuilds_custom_stats_equal_to_a_recount_of_etl_actions(store):
    upstream = two_matches()
    rules = [Rule.model_validate({'match_id': MATCH, 'operation': 'count', 'predicates': [
        {'field': 'action_type', 'op': 'eq', 'value': kind}, *extra]})
        for kind, extra in (('pass', []), ('shot', [{'field': 'result', 'op': 'eq', 'value': 'fail'}]),
                            ('corner_crossed', []), ('shot', [{'field': 'result', 'op': 'eq', 'value': 'success'}]))]
    with Running(store, upstream=upstream, matches=(MATCH, OTHER)) as run:
        run.send(8)
        for rule in rules[:2]:
            assert run.client.post(f'/lab/matches/{MATCH}/calculations', json={'rule': rule.model_dump(mode='json')}).status_code == 201
        run.send(10)
        for rule in rules[2:]:
            run.client.post(f'/lab/matches/{MATCH}/calculations', json={'rule': rule.model_dump(mode='json')})
        run.send(17, commit=False)  # Received, not yet at ETL: its actions are unreachable.
        live = {c['id']: c['value'] for c in run.client.get(f'/lab/matches/{MATCH}/state').json()['calculations']}
    with Running(store, upstream=upstream, matches=()) as run:
        match = run.match()
        assert match.seq == 35
        restored = {c['id']: c['value'] for c in run.client.get(f'/lab/matches/{MATCH}/state').json()['calculations']}
        assert match.actions_seq == 18 and all(a.final_seq <= 18 for a in match.actions)
        recount = {rule.calculation_id: FilterEngine().register(rule, match.actions).value for rule in rules}
        assert restored == live == recount and any(recount.values())
        run.send(0)
        # The stream continues where it stopped; nothing is replayed from a recording.
        upstream.matches[MATCH].sent = 35
        assert run.registry.get(OTHER).seq == 0


def test_actions_that_do_not_continue_the_held_ones_recount_from_etl_instead_of_wedging(store):
    """Live: a projection once held fewer actions than its SPADL watermark said and raised "out of order" on every
    later read. A read that does not continue the held actions now rebuilds and recounts them once."""
    upstream = two_matches()
    rule = Rule.model_validate({'match_id': MATCH, 'operation': 'count',
                                'predicates': [{'field': 'action_type', 'op': 'eq', 'value': 'pass'}]})
    with Running(store, upstream=upstream, matches=(MATCH, OTHER)) as run:
        run.send(10)
        assert run.client.post(f'/lab/matches/{MATCH}/calculations', json={'rule': rule.model_dump(mode='json')}).status_code == 201
        run.client.get(f'/lab/matches/{MATCH}/state')
        match = run.match()
        assert match.actions
        del match.actions[-1]  # Held actions no longer reach the actions watermark.
        run.send(17)
        state = run.client.get(f'/lab/matches/{MATCH}/state')
        assert state.status_code == 200
        assert [a.action_id for a in match.actions] == list(range(len(match.actions)))
        assert match.actions_seq == match.seq
        value = next(c['value'] for c in state.json()['calculations'])
        assert value == FilterEngine().register(rule, match.actions).value


def test_no_future_data_is_reachable(store):
    agent = Recorder()
    with Running(store, agent=agent) as run:
        run.send(10)
        run.send(20, commit=False)
        token = start(run.client)['session_token']
        reply = ask(run.client, token, 'show the shots')
        assert reply['snapshot']['seq'] == 10
        # Actions listed to the agent stop at the snapshot; ETL refuses stats past its watermark.
        actions = run.client.portal.call(run.app.state.questions.match_data.actions,
                                         type('S', (), {'id': f'{MATCH}:10', 'match_id': MATCH, 'seq': 10})())
        assert actions['items'] and all(a['final_seq'] <= 10 for a in actions['items'])
        future = run.client.portal.call(run.upstream.dab.stats_at_seq, MATCH, 11)
        assert future == []
        # MA3 cards and goals are bounded by eventSeq in the database query, not trimmed afterwards.
        assert 'eventSeq: {lte: $s}' in etl_dab.RAW
        cards = run.client.portal.call(run.upstream.dab.cards, MATCH, 10)
        assert all(c['seq'] <= 10 for c in cards)
        assert run.client.get(f'/lab/matches/{MATCH}/events/31').status_code == 404
        # A narrative written from later data stays hidden.
        deliver(run, narrative(MATCH, event_seq=11, text='Later.'))
        refresh(run)
        assert run.client.get(path(token)).json()['snapshot']['narratives'] == []


def test_purge_tombstones_closes_sockets_and_never_revives(store):
    with Running(store, upstream=two_matches(), matches=(MATCH, OTHER)) as run:
        run.send(5)
        run.send(5, OTHER)
        token = start(run.client)['session_token']
        other = start(run.client, OTHER)['session_token']
        lab_ask(run.client, session(run.client, profile='united-casual'), 'what is offside')
        assert run.client.post('/admin/matches/purge', json={}).status_code == 422
        assert run.client.post('/admin/matches/purge', json={'match_id': MATCH, 'all': True}).status_code == 422
        with run.client.websocket_connect(path(token) + '/live') as ws:
            ws.receive_json()
            purged = run.client.post('/admin/matches/purge', json={'match_id': MATCH}).json()
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4404
        assert purged['match_ids'] == [MATCH]
        assert purged['purged']['received_events'] == 5 and purged['purged']['question_sessions'] == 2
        assert run.client.get(path(token)).status_code == 404
        assert run.client.get(path(other, OTHER)).status_code == 200  # The other match is untouched.
        # Late messages for a tombstoned match are dropped, never re-creating rows.
        run.client.portal.call(run.upstream.kickoff, run.registry, MATCH)
        run.send(1)
        assert MATCH not in run.registry.matches
        assert MATCH not in [m['match_id'] for m in run.client.get('/product/matches').json()]
        assert run.client.post('/admin/matches/purge', json={'match_id': 'never-seen-00000000'}).json() == {
            'match_ids': ['never-seen-00000000'], 'purged': {k: 0 for k in purged['purged']}}
        # Purge all: every known match, plus a cut-off for MA1s sent before it.
        everything = run.client.post('/admin/matches/purge', json={'all': True}).json()
        assert everything['match_ids'] == [OTHER] and not run.registry.matches
        run.upstream.add('late-11111111')
        run.client.portal.call(lambda: run.upstream.kickoff(run.registry, 'late-11111111', sent_at='2000-01-01T00:00:00Z'))
        assert 'late-11111111' not in run.registry.matches
        run.client.portal.call(run.upstream.kickoff, run.registry, 'late-11111111')
        assert 'late-11111111' in run.registry.matches
        # Configuration stays.
        assert run.client.get('/dev/config/presentation').status_code == 200
        assert len(run.client.get('/product/profiles').json()['profiles']) == 3


def test_messages_for_unknown_matches_and_old_envelopes_are_dropped(store):
    with Running(store, matches=()) as run:
        event = run.upstream.add(MATCH).event(1).model_dump(mode='json')
        v2 = {'type': 'MatchEvent', 'version': 2, 'matchId': MATCH, 'seq': 1, 'event': event}
        run.client.portal.call(handle_match_message, json.dumps(v2), None, run.registry)
        assert MATCH not in run.registry.matches  # No MA1 yet.
        run.client.portal.call(run.upstream.kickoff, run.registry, MATCH)
        for body in ({**v2, 'version': 1}, {**v2, 'seq': 2}, {**v2, 'matchId': 'x'}, 'not json', {'feed': 'POS'}):
            run.client.portal.call(handle_match_message, json.dumps(body) if isinstance(body, dict) else body, None, run.registry)
        assert run.match().seq == 0
        run.client.portal.call(handle_match_message, json.dumps(v2), None, run.registry)
        run.client.portal.call(handle_match_message, json.dumps(v2), None, run.registry)  # redelivery
        assert run.match().seq == 1


def test_no_runtime_module_opens_recordings_or_fixtures():
    """The feed is an external provider: the runtime reads no recording, test fixture or double."""
    banned = ('recordings', 'filter-lab', 'product-demo', 'DEMO_RECORDING', 'OPTA_STREAM', 'HLS_PUBLISH',
              'BACKEND_MODE', '.jsonl', 'm3u8')
    for file in BACKEND.rglob('*.py'):
        tree = ast.parse(file.read_text())
        imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert not any(name.startswith(('benchmarks', 'tests')) for name in imports), file
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and node.body and isinstance(node.body[0], ast.Expr)}
        strings = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                   and isinstance(node.value, str) and id(node) not in docstrings]
        for word in banned:
            assert not any(word in text for text in strings if not (word == 'm3u8' and file.name == 'hls_media.py')), \
                f'{file.name} names {word}'
    # Recording adapters and the unused coding-agent contract live in benchmarks/.
    assert not (BACKEND / 'adapters' / 'events.py').exists() and not (BACKEND / 'coding.py').exists()


def test_a_seed_restores_under_a_new_match_id_and_carries_on(store):
    """PLAN.md §10.6: export one match, purge everything, load it as another; it serves the same story and
    takes the next events from its stream."""
    with Running(store, upstream=two_matches(), matches=(MATCH, OTHER), enable_demo_seeds=True) as run:
        run.send(20)
        deliver(run, narrative(MATCH, event_seq=20, text='Chelsea story.'))
        exported = run.client.post('/admin/matches/export', json={'match_id': MATCH}).json()
        seed, schema = exported['tables'], exported['schema']
        assert len(seed['received_events']) == 20 and len(seed['engine_narratives']) == 1
        assert not set(seed) & {'subscriptions', 'question_sessions', 'match_calculations'}  # viewers' own
        run.client.post('/admin/matches/purge', json={'all': True})  # its cut-off is later than the seed's MA1
        new = 'seeded-aaaa1111'
        moved = json.loads(json.dumps(seed).replace(MATCH, new))

        def restore(match_id, tables, max_seq=20, schema=schema):
            return run.client.post('/admin/matches/restore', json={'match_id': match_id, 'max_seq': max_seq,
                                                                   'schema': schema, 'tables': tables})
        assert restore(new, moved, 19).status_code == 409  # events past the seed's seq
        assert restore(new, moved, schema='other').status_code == 409  # another schema
        assert restore(MATCH, seed).status_code == 409  # tombstoned
        restored = restore(new, moved)
        assert restored.status_code == 200 and restored.json()['restored']['received_events'] == 20
        assert restore(new, moved).status_code == 409  # known now
        assert run.registry.matches[new].seq == 20
        again = run.client.post('/admin/matches/export', json={'match_id': new}).json()
        assert again == {'match_id': new, 'schema': schema, 'tables': moved}  # the recorded state, row for row
        assert not run.registry.matches[new].purged
        run.client.post('/admin/matches/purge', json={'match_id': new})
        assert new not in run.registry.matches
        assert not any(run.client.post('/admin/matches/export', json={'match_id': new}).json()['tables'].values())


class ShownEvidence:
    """A replay plan citing an action the question context shows (as `action:{id}`) without searching,
    the way a model answers 'show me that' on a restored match whose story is already told."""
    mode = 'fixture'

    async def answer(self, prompt, context, tools):
        from backend.agents.question import replay_draft
        from backend.agents.replay import ReplayDecision, finish
        await tools.replay.match_state()
        tools.replay.cite_shown(context)
        shown = context['compact']['tail'][-1]['evidence_id']
        return replay_draft(finish(ReplayDecision(status='answer', text='That moment.',
                                                  items=[{'source_id': shown, 'kind': 'event'}]), tools.replay))


def test_a_restored_match_answers_replay_questions(store):
    """A seeded match serves replays from its restored actions, by search and from the events it shows."""
    with Running(store, upstream=two_matches(), matches=(MATCH, OTHER), enable_demo_seeds=True) as run:
        run.send(30)
        exported = run.client.post('/admin/matches/export', json={'match_id': MATCH}).json()
        run.client.post('/admin/matches/purge', json={'all': True})
        new = 'seeded-bbbb2222'
        moved = json.loads(json.dumps(exported['tables']).replace(MATCH, new))
        restored = run.client.post('/admin/matches/restore', json={'match_id': new, 'max_seq': 30,
                                                                   'schema': exported['schema'], 'tables': moved})
        assert restored.status_code == 200
        etl = run.upstream.add(new, timed())  # ETL holds the restored rows (its own seed) up to the seed's seq
        etl.sent = etl.committed = 30
        refresh(run, new)
        viewer = start(run.client, new)
        run.app.state.questions.agent = Recorder()
        searched = ask(run.client, viewer['session_token'], 'show the shots', new)
        assert searched['status'] == 'answer' and searched['replay']['items']
        run.app.state.questions.agent = ShownEvidence()
        shown = ask(run.client, viewer['session_token'], 'show me that', new)
        assert shown['status'] == 'answer' and len(shown['replay']['items']) == 1


def test_seed_routes_exist_only_with_the_demo_setting(store):
    """A production release (DEMO_SEEDS off) has no export or restore route."""
    with Running(store) as run:
        for path in ('/admin/matches/export', '/admin/matches/restore'):
            assert run.client.post(path, json={'match_id': MATCH}).status_code == 404
        assert run.client.post('/admin/matches/purge', json={'match_id': MATCH}).status_code == 200
