"""Viewer product per match: shared projection, durable private pins, sessions per (viewer, profile, match)."""
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketDisconnect

from backend.models.rules import Rule
from harness import MATCH, Running, Upstream
from support import OTHER, VIEWER, ask, deliver, narrative, path, refresh, start, until

def test_product_maps_relative_profile_and_cites_the_snapshot(store):
    with Running(store) as run:
        data = start(run.client)
        snapshot = data['snapshot']
        assert snapshot['match']['id'] == data['match_id'] == MATCH
        assert snapshot['bucket_id'] == 'home:analytical' and snapshot['profile']['team'] == 'riverton'
        assert 'bucket' not in snapshot and snapshot['snapshot_id'] == f'{MATCH}:0'
        assert [c['id'] for c in snapshot['cards']] == ['riverton:goals', 'riverton:shots', 'riverton:corners',
                                                        'riverton:passes', 'riverton:cards']
        assert all(c['value'] == 0 for c in snapshot['cards'])
        assert snapshot['match']['teams'][0]['branding']['crest_asset_id'] == 'riverton'
        assert snapshot['match']['media']['url'] is None  # This feed has no video capability.
        reply = ask(run.client, data['session_token'], 'what is offside')
        assert reply['snapshot']['match_id'] == MATCH


def test_match_list_comes_from_etl_and_known_matches(store):
    with Running(store, matches=(MATCH, OTHER)) as run:
        run.send(10, MATCH)
        run.upstream.add('unknown-ffffffff')  # ETL knows it, but its MA1 never reached this service.
        rows = run.client.get('/product/matches').json()
        assert [r['match_id'] for r in rows] == [MATCH, OTHER]  # live first, then scheduled
        assert rows[0]['status'] == 'live' and rows[0]['seq'] == 10 and rows[1]['seq'] == 0
        assert [t['score'] for t in rows[0]['teams']] == [0, 0] and rows[0]['teams'][0]['code'] == 'RIV'  # the harness codes a team by its name's first letters
        assert run.client.get('/product/matches/unknown-ffffffff/sessions/' + str(uuid4())).status_code == 404


def test_all_five_standard_values_are_passed_through_from_etl(store):
    with Running(store) as run:
        data_port = run.app.state.questions.match_data
        original = data_port.stats

        async def supplied(snapshot):
            result = await original(snapshot)
            return {**result, 'stats': [{**s, 'value': 1000 + i} for i, s in enumerate(result['stats'])]}
        data_port.stats = supplied
        data = start(run.client)
        supplied_values = {s['id']: s['value'] for s in run.app.state.product.projections[MATCH].shared['stats']}
        assert len(data['snapshot']['cards']) == 5
        assert all(card['value'] == supplied_values[card['id']] >= 1000 for card in data['snapshot']['cards'])
        assert run.client.get(path(data['session_token'])).json()['snapshot']['cards'] == data['snapshot']['cards']


def test_pins_are_durable_private_and_restore_standard_slot(store):
    with Running(store) as run:
        data = start(run.client)
        token = data['session_token']
        offer = ask(run.client, token, "Track Mbappe's headed shots")['offers'][0]
        response = run.client.post(path(token) + f'/offers/{offer["id"]}/track').json()
        calculation = response['calculation']['id']
        assert [c['kind'] for c in response['snapshot']['cards']] == ['standard'] * 4 + ['custom']
        run.send(35)
        refresh(run)
        restored = run.client.get(path(token)).json()
        assert restored['snapshot']['cards'][-1]['value'] == 3
        other = start(run.client, profile='neutral-simple')
        assert all(c['kind'] == 'standard' for c in other['snapshot']['cards'])
        assert run.client.post(path(other['session_token']) + f'/offers/{offer["id"]}/track').status_code == 404
        again = start(run.client)
        assert again['snapshot']['cards'][-1]['id'] == calculation
        unpin = run.client.delete(path(again['session_token']) + f'/pins/{calculation}').json()
        assert len(unpin['snapshot']['cards']) == 5 and all(c['kind'] == 'standard' for c in unpin['snapshot']['cards'])


def test_socket_push_takeover_and_unknown_session_codes(store):
    with Running(store) as run:
        token = start(run.client)['session_token']
        with run.client.websocket_connect(path(token) + '/live') as ws:
            initial = ws.receive_json()
            assert initial['match']['seq'] == 0
            run.send(1)
            updated = until(ws, lambda m: m['match']['seq'] == 1)
            assert updated['version'] > initial['version']
            # The lab chat is its own viewer; the same browser opening the match again takes the session over.
            run.client.post(f'/lab/matches/{MATCH}/chat/sessions', json={'profile_id': 'riverton-analytical'})
            start(run.client)
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4001
        with run.client.websocket_connect(path(uuid4()) + '/live') as ws, pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4001
        with run.client.websocket_connect(path(uuid4(), 'unknown-ffffffff') + '/live') as ws, \
                pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4404


def test_two_browsers_on_one_profile_are_two_viewers_and_never_take_each_other_over(store):
    ALICE, BOB = str(uuid4()), str(uuid4())

    def begin(viewer):
        response = run.client.post(f'/product/matches/{MATCH}/sessions',
                                   json={'profile_id': 'riverton-analytical', 'viewer_id': viewer})
        assert response.status_code == 200, response.text
        return response.json()['session_token']
    with Running(store) as run:
        alice, bob = begin(ALICE), begin(BOB)
        with run.client.websocket_connect(path(alice) + '/live') as ws:
            ws.receive_json()
            assert begin(BOB) != bob  # Bob reconnecting replaces only Bob's own session
            run.send(1)
            assert until(ws, lambda m: m['match']['seq'] == 1)  # Alice's socket stays open
            ask(run.client, alice, 'How many shots has Riverton Rovers had?')
            assert run.client.get(path(alice)).status_code == 200
            bob = begin(BOB)
            assert [t['prompt'] for t in run.client.get(path(bob)).json()['turns']] == []  # no crossed questions
            begin(ALICE)  # the same browser opening again takes its own session over
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4001
        assert run.client.get(path(alice)).status_code == 409
        for bad in ('bad id!', 'browser-a', '', None):  # only a random UUID: a guessable id could reopen another's chat
            body = {'profile_id': 'riverton-analytical'} | ({} if bad is None else {'viewer_id': bad})
            assert run.client.post(f'/product/matches/{MATCH}/sessions', json=body).status_code == 422


def test_projection_work_is_shared_and_corrections_remove_retracted_goal(store):
    with Running(store) as run:
        first, second = start(run.client), start(run.client, profile='neutral-simple')
        reads = []
        data_port = run.app.state.questions.match_data
        original = data_port.stats

        async def count(snapshot):
            reads.append(snapshot.seq)
            return await original(snapshot)
        data_port.stats = count
        with run.client.websocket_connect(path(first['session_token']) + '/live') as a, \
                run.client.websocket_connect(path(second['session_token']) + '/live') as b:
            a.receive_json(), b.receive_json()
            run.send(1)
            until(a, lambda m: m['match']['seq'] == 1), until(b, lambda m: m['match']['seq'] == 1)
            assert reads.count(1) == 1  # One ETL read per snapshot, shared by every viewer.
        run.send(34)
        refresh(run)
        view = run.client.get(path(first['session_token'])).json()['snapshot']
        assert [t['score'] for t in view['match']['teams']] == [1, 0]
        assert not any(e['deleted'] for e in view['events'])
        assert view['match']['status'] in ('live', 'finished')


def test_unconfirmed_events_wait_for_etl_and_projection_catches_up(store):
    with Running(store) as run:
        token = start(run.client)['session_token']
        run.send(5)
        run.send(5, commit=False)
        refresh(run)
        assert run.client.get(path(token)).json()['snapshot']['match']['seq'] == 5
        run.upstream.matches[MATCH].committed = 10
        refresh(run)
        assert run.client.get(path(token)).json()['snapshot']['match']['seq'] == 10


def test_engine_narratives_route_by_bucket_and_never_pass_the_snapshot(store):
    with Running(store, matches=(MATCH, OTHER)) as run:
        token = start(run.client)['session_token']
        run.send(10)
        assert deliver(run, narrative(MATCH, event_seq=10, text='Now.'))
        assert deliver(run, narrative(MATCH, seq=2, event_seq=11, text='Future.'))
        assert deliver(run, narrative(MATCH, bucket='away:simple', seq=3, event_seq=1, text='Other bucket.'))
        assert deliver(run, narrative(OTHER, event_seq=1, text='Other match.'))
        assert not deliver(run, narrative('never-announced-00000000', event_seq=1))
        assert not deliver(run, narrative(MATCH, event_seq=10, text='Now.'))  # duplicate id
        refresh(run)
        texts = [n['text'] for n in run.client.get(path(token)).json()['snapshot']['narratives']]
        assert texts == ['Now.']
        run.send(1)
        refresh(run)
        texts = [n['text'] for n in run.client.get(path(token)).json()['snapshot']['narratives']]
        assert texts == ['Now.', 'Future.']


def test_the_narrative_cap_is_per_bucket_so_a_busy_bucket_never_trims_another(store):
    from types import SimpleNamespace
    from backend.repositories.engine_narratives import EngineNarratives
    with Running(store) as run:
        run.send(10)
        for seq in range(1, 6):
            assert deliver(run, narrative(MATCH, seq=seq, minute=seq, event_seq=seq, text=f'Home {seq}.'))
        assert deliver(run, narrative(MATCH, bucket='away:simple', seq=9, minute=0, event_seq=1, text='Away old.'))
        snapshot = SimpleNamespace(match_id=MATCH, seq=10, period=1, clock_seconds=600)
        items = EngineNarratives(store).items(snapshot, per_bucket=2)
        assert [n['text'] for n in items] == ['Away old.', 'Home 4.', 'Home 5.']  # newest two each, oldest first


def test_period_end_releases_that_periods_narratives(store):
    import json
    from benchmarks.doubles.recording import FixtureEventSource
    spec = json.loads(FixtureEventSource().content)
    spec['presets'] = []
    spec['events'] = spec['events'][:34] + [{**spec['events'][33], 'eventId': 'end-2', 'typeName': 'period_end',
                                             'teamId': None, 'playerId': None, 'qualifiers': [], 'outcome': None,
                                             'periodId': 2, 'timeMin': 95, 'timeSec': 10}]
    upstream = Upstream()
    upstream.add(MATCH, FixtureEventSource(content=json.dumps(spec).encode()))
    with Running(store, upstream=upstream) as run:
        token = start(run.client)['session_token']
        run.send(35)  # The last event ends the second (final) period.
        # A full-time step written at the minute's last second, after the final event's clock.
        assert deliver(run, narrative(MATCH, minute=199, second=59, text='Full time.', period=2))
        refresh(run)
        view = run.client.get(path(token)).json()['snapshot']
        assert 'Full time.' in [n['text'] for n in view['narratives']] and view['match']['status'] == 'finished'


def test_pin_limit_and_duplicate_tracking(store):
    with Running(store) as run:
        token = start(run.client)['session_token']
        repository = run.app.state.questions.repository
        offers = []
        for i, kind in enumerate(('pass', 'shot', 'corner_crossed', 'keeper_save', 'tackle', 'clearance')):
            rule = Rule.model_validate({'match_id': MATCH, 'operation': 'count',
                                        'predicates': [{'field': 'action_type', 'op': 'eq', 'value': kind}]})
            turn = repository.begin(token, uuid4(), f'Test {i}')
            offer = {'id': str(uuid4()), 'match_id': MATCH, 'rule': rule.model_dump(mode='json'), 'label': kind, 'value': 0}
            repository.finish(token, turn['id'], {'status': 'answer', 'text': kind, 'offers': [offer]})
            offers.append(offer)
        for offer in offers[:5]:
            assert run.client.post(path(token) + f'/offers/{offer["id"]}/track').status_code == 200
        assert run.client.post(path(token) + f'/offers/{offers[0]["id"]}/track').status_code == 200
        sixth = run.client.post(path(token) + f'/offers/{offers[5]["id"]}/track')
        assert sixth.status_code == 409 and sixth.json()['code'] == 'cards_full'
        assert run.match().engine.count == 5


def test_card_presentation_comes_from_configuration(store):
    with Running(store) as run:
        current = run.client.get('/dev/config/presentation').json()
        value = {**current['value'], 'card_slots': 3,
                 'default_stats': {'team': ['{team}:passes', '{team}:goals', '{team}:shots'],
                                   'neutral': ['all:passes', 'all:goals', 'all:shots']}}
        saved = run.client.put('/dev/config/presentation', json={'value': value, 'expected_revision': current['revision']})
        assert saved.status_code == 200 and saved.json()['revision'] == current['revision'] + 1
        assert run.client.put('/dev/config/presentation',
                              json={'value': value, 'expected_revision': current['revision']}).status_code == 409
        assert [c['id'] for c in start(run.client)['snapshot']['cards']] == ['riverton:passes', 'riverton:goals', 'riverton:shots']
        neutral = [c['id'] for c in start(run.client, profile='neutral-simple')['snapshot']['cards']]
        assert neutral == ['all:passes', 'all:goals', 'all:shots'] and 'all:possession' not in neutral


def test_bootstrap_upstream_failure_is_retryable(store):
    with Running(store) as run:
        async def unavailable(*args, **kwargs):
            raise RuntimeError('upstream unavailable')
        run.app.state.questions.match_data.stats = unavailable
        failed = run.client.post(f'/product/matches/{MATCH}/sessions', json={'profile_id': 'riverton-analytical', 'viewer_id': VIEWER})
        assert failed.status_code == 503 and failed.json()['code'] == 'snapshot_unavailable'


def test_unpin_revision_fences_older_queued_snapshots(store):
    with Running(store) as run:
        token = start(run.client)['session_token']
        offer = ask(run.client, token, "Track Mbappe's headed shots")['offers'][0]
        calculation_id = run.client.post(path(token) + f'/offers/{offer["id"]}/track').json()['calculation']['id']
        before = run.client.get(path(token)).json()['snapshot']
        removed = run.client.delete(path(token) + f'/pins/{calculation_id}').json()['snapshot']
        assert removed['version'] > before['version']
        assert all(card['kind'] == 'standard' for card in removed['cards'])


def test_restart_changes_projection_epoch_not_the_match(store):
    upstream = Upstream()
    with Running(store, upstream=upstream) as run:
        token = start(run.client)['session_token']
        run.send(4)
        refresh(run)
        before = run.client.get(path(token)).json()['snapshot']
    with Running(store, upstream=upstream, matches=()) as run:
        after = run.client.get(path(token)).json()['snapshot']
        assert after['match']['seq'] == before['match']['seq'] == 4
        assert after['projection_epoch'] != before['projection_epoch']


def test_standard_offer_pins_upstream_value_and_streams_without_custom_engine(store):
    with Running(store) as run:
        data_port = run.app.state.questions.match_data
        original = data_port.stats

        async def supplied(snapshot):
            result = await original(snapshot)
            return {**result, 'stats': [{**s, 'value': 1000 + snapshot.seq} if s['id'] == 'all:shots' else s
                                        for s in result['stats']]}
        data_port.stats = supplied

        async def forbidden(*args, **kwargs):
            raise AssertionError('An ETL pin must not compile a rule')
        run.service.planner.plan = forbidden
        token = start(run.client)['session_token']
        offer = ask(run.client, token, 'how many Both teams shots')['offers'][0]
        assert offer['kind'] == 'standard' and offer['value'] == 1000 and 'rule' not in offer
        run.send(1)
        tracked = run.client.post(path(token) + f'/offers/{offer["id"]}/track').json()
        assert tracked['calculation']['id'] == 'standard:all:shots' and tracked['calculation']['value'] == 1001
        card = tracked['snapshot']['cards'][-1]
        assert card['id'] == 'all:shots' and card['value'] == 1001 and card['pin_id'] == 'standard:all:shots'
        assert run.match().engine.count == 0


def test_tracking_a_stat_never_displaces_the_goals_card():
    from backend.services.product import MatchProjection
    from benchmarks.doubles.config import seeded
    projection = MatchProjection.__new__(MatchProjection)
    kinds = ('possession', 'pass_accuracy', 'shots', 'passes', 'goals', 'tackles')
    presentation = seeded('presentation')
    # Goals is the lowest-priority default, so only its protection keeps it.
    defaults = presentation.default_stats.model_copy(update={'team': ['{team}:' + k for k in kinds[:5]]})
    projection.presentation = presentation.model_copy(update={'default_stats': defaults})
    projection.buckets = []
    stats = [{'id': f'riverton:{k}', 'label': k, 'value': 1} for k in kinds]
    projection.shared = {'type': 'snapshot', 'version': 1, 'projection_epoch': 'e', 'synthetic': True, 'mode': 'local',
                         'snapshot_id': 'm:1', 'match': {'teams': [{'id': 'riverton'}, {'id': 'forgeham'}]}, 'events': [],
                         'stats': stats, 'calculations': {}, 'narratives': []}
    viewer = {'profile': {'team': 'riverton', 'selections': {'team': 'home', 'fan_style': 'analytical'}},
              'audience': {'bucket_id': 'home:analytical', 'selections': {'team': 'home', 'fan_style': 'analytical'}},
              'offers': []}
    assert [c['id'] for c in projection.compose(viewer)['cards']][-1] == 'riverton:goals'
    viewer['offers'] = [{'calculation_id': 'pin', 'kind': 'standard', 'standard_stat_id': 'riverton:tackles', 'label': 'Tackles'}]
    assert [c['id'] for c in projection.compose(viewer)['cards']] == [
        'riverton:possession', 'riverton:pass_accuracy', 'riverton:shots', 'riverton:goals', 'riverton:tackles']


def test_default_cards_show_both_teams_in_one_slot():
    """A default card is one slot showing its kind for home and away; a team row that is missing or incomplete
    shows nothing for that side; the label loses its team prefix."""
    from backend.services.product import MatchProjection
    from benchmarks.doubles.config import seeded
    projection = MatchProjection.__new__(MatchProjection)
    projection.presentation = seeded('presentation').model_copy(update={'card_slots': 2})
    projection.buckets = []
    stats = [{'id': 'all:goals', 'label': 'Both teams goals', 'value': 3},
             {'id': 'riverton:goals', 'label': 'Riverton Rovers goals', 'value': 2},
             {'id': 'forgeham:goals', 'label': 'Forgeham United goals', 'value': 1},
             {'id': 'all:shots', 'label': 'Both teams shots', 'value': 9},
             {'id': 'riverton:shots', 'label': 'Riverton Rovers shots', 'value': 9},
             {'id': 'forgeham:shots', 'label': 'Forgeham United shots', 'value': 4, 'complete': False}]
    teams = [{'id': 'riverton', 'name': 'Riverton Rovers'}, {'id': 'forgeham', 'name': 'Forgeham United'}]
    projection.shared = {'type': 'snapshot', 'version': 1, 'projection_epoch': 'e', 'synthetic': True, 'mode': 'local',
                         'snapshot_id': 'm:1', 'match': {'teams': teams}, 'events': [],
                         'stats': stats, 'calculations': {}, 'narratives': []}
    viewer = {'profile': {'team': 'riverton', 'selections': {}}, 'audience': {'bucket_id': 'home:analytical'}, 'offers': []}
    cards = projection.compose(viewer)['cards']
    assert [c['id'] for c in cards] == ['riverton:goals', 'riverton:shots']
    assert [c['label'] for c in cards] == ['Goals', 'Shots']
    assert [[s['value'] for s in c['sides']] for c in cards] == [[2, 1], [9, None]]
    assert [s['team_id'] for s in cards[0]['sides']] == ['riverton', 'forgeham']
    neutral = projection.compose({**viewer, 'profile': {'team': None, 'selections': {}}})['cards']
    assert [(c['id'], c['label'], c['value']) for c in neutral] == [('all:goals', 'Goals', 3), ('all:shots', 'Shots', 9)]
    assert [s['value'] for s in neutral[0]['sides']] == [2, 1]
    # A tracked standard stat stays a single value.
    viewer['offers'] = [{'calculation_id': 'pin', 'kind': 'standard', 'standard_stat_id': 'forgeham:shots', 'label': 'Shots'}]
    assert 'sides' not in projection.compose(viewer)['cards'][-1]


def test_a_match_link_opens_before_kickoff_and_goes_live(store):
    """Before MA1 a link is `match_not_started` (purged stays `match_not_found`); after MA1 the
    viewer gets a scheduled pre-match snapshot with the kickoff, then live play on the socket."""
    with Running(store, matches=()) as run:
        run.upstream.add(MATCH)
        early = run.client.post(f'/product/matches/{MATCH}/sessions', json={'profile_id': 'riverton-analytical', 'viewer_id': VIEWER})
        assert early.status_code == 404 and early.json()['code'] == 'match_not_started'
        run.client.portal.call(run.upstream.kickoff, run.registry, MATCH)
        data = start(run.client)
        match = data['snapshot']['match']
        assert match['status'] == 'scheduled' and match['clock_seconds'] is None
        assert match['scheduled_kickoff'] == '2026-10-20T15:00:00.000Z'
        assert [t['name'] for t in match['teams']] == ['Riverton Rovers', 'Madrid']
        with run.client.websocket_connect(path(data['session_token']) + '/live') as ws:
            ws.receive_json()
            run.send(1)
            assert until(ws, lambda m: m.get('type') == 'snapshot' and m['match']['status'] == 'live')['match']['seq'] == 1
        run.client.post('/admin/matches/purge', json={'match_id': MATCH})
        gone = run.client.post(f'/product/matches/{MATCH}/sessions', json={'profile_id': 'riverton-analytical', 'viewer_id': VIEWER})
        assert gone.status_code == 404 and gone.json()['code'] == 'match_not_found'
