"""Story follows: feed rules, one follow per viewer, ownership, the engine's targets, the follow chat, purge."""
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

from backend.adapters.ma3 import key_moment
from backend.models.config import KeyMomentFeed
from backend.models.engine_narratives import EngineFollowClip, EngineMomentClip, EngineNarrative
from backend.services.key_moments import feed_moments
from harness import MATCH, Running, Upstream, timed

OTHER = 'north-south-0badc0de'
STORYLINE = {'id': f'sl:{MATCH}:1', 'label': 'Madrid control the midfield', 'team': 'madrid', 'status': 'active',
             'salienceHistory': [{'at': {'periodId': 1, 'timeMin': 4}, 'salience': 0.9}], 'outcome': None,
             'keyEventIds': [], 'openedAt': {'periodId': 1, 'timeMin': 4},
             'updatedAt': {'periodId': 1, 'timeMin': 9}, 'resolvedAt': None,
             'beats': [{'at': {'periodId': 1, 'timeMin': 4}, 'headline': 'Madrid hold the ball'}]}
TEAM = {'kind': 'team', 'team_id': 'chelsea', 'label': 'Chelsea'}
PLAYER = {'kind': 'player', 'player_id': 'mbappe', 'label': 'Kylian Mbappé'}


def start(client, profile='chelsea-analytical', match_id=MATCH):
    response = client.post(f'/product/matches/{match_id}/sessions', json={'profile_id': profile})
    assert response.status_code == 200, response.text
    return response.json()


def path(token, match_id=MATCH):
    return f'/product/matches/{match_id}/sessions/{token}'


def follow(client, token, spec, match_id=MATCH):
    return client.post(path(token, match_id) + '/follows', json={'spec': spec})


def narrative(match_id=MATCH, bucket='home:analytical', seq=1, text='Insight.', topic=None, event_seq=1):
    kind = {'kind': 'subscription', 'topicId': topic} if topic else {}
    return EngineNarrative.model_validate({
        'id': f"{'sub' if topic else 'narr'}:{match_id}:{topic or ''}:{bucket}:{seq}", 'matchId': match_id,
        'userType': bucket, 'seq': seq, 'stepId': f'{match_id}:step:{seq}',
        'trigger': {'type': 'scheduled', 'ref': 'r', 'reason': 'r'}, 'matchTime': {'periodId': 1, 'timeMin': 0},
        'text': text, 'createdAt': f'2026-10-20T00:00:{seq:02d}Z', 'timeSec': 30, 'eventSeq': event_seq, **kind})


def deliver(run, item):
    return run.client.portal.call(run.app.state.product.narrative, item)


def view(run, token, match_id=MATCH):
    async def go():
        await run.app.state.product.projection(match_id).refresh()
    run.client.portal.call(go)
    return run.client.get(path(token, match_id)).json()['snapshot']


def test_feed_rules_follow_replaces_insights_and_key_moments_show_for_everyone(store):
    with Running(store) as run:
        run.narratives.storylines[MATCH] = [STORYLINE]
        token = start(run.client)['session_token']
        run.send(25)
        topic = follow(run.client, token, TEAM).json()['follow']['topic_id']
        follow(run.client, start(run.client, 'united-casual')['session_token'], TEAM)
        assert deliver(run, narrative(text='Bucket insight.'))
        assert deliver(run, narrative(topic=topic, text='Chelsea story.'))
        assert deliver(run, narrative(topic=topic, bucket='away:casual', text='Other bucket.'))
        assert not deliver(run, narrative(topic='topic:' + '0' * 16, text='Unknown topic.'))
        snapshot = view(run, token)
        assert snapshot['feed_mode'] == 'following' and snapshot['follow']['topic_id'] == topic
        assert [n['text'] for n in snapshot['narratives']] == ['Chelsea story.']
        # Key moments are ETL facts at the snapshot: a yellow card is not pivotal; the retracted goal (seq 7-8) is gone.
        assert [(m['kind'], m['label']) for m in snapshot['key_moments']] == [
            ('red_card', 'Red card · Levi Colwill'), ('goal', 'Goal · Chelsea · Cole Palmer')]
        assert [m['event_seq'] for m in snapshot['key_moments']] == [21, 24]
        subscription = snapshot['follow']['subscription_id']
        response = run.client.delete(path(token) + f'/follows/{subscription}')
        assert response.status_code == 200 and response.json()['snapshot']['feed_mode'] == 'insights'
        snapshot = view(run, token)
        assert [n['text'] for n in snapshot['narratives']] == ['Bucket insight.'] and snapshot['key_moments']


def test_key_moments_never_pass_the_snapshot(store):
    with Running(store) as run:
        token = start(run.client)['session_token']
        run.send(6)
        assert view(run, token)['key_moments'] == []
        run.send(17)
        assert [m['kind'] for m in view(run, token)['key_moments']] == ['red_card']
        run.send(3)
        assert [m['kind'] for m in view(run, token)['key_moments']] == ['red_card', 'goal']



def clip_narrative(topic, moment_id, event_seq, bucket='home:analytical', seq=1):
    """A follow narrative written on a key event whose verdict carried `clip` (the clip itself is its own message)."""
    return EngineNarrative.model_validate({
        'id': f'sub:{MATCH}:{topic}:{bucket}:{seq}', 'matchId': MATCH, 'userType': bucket, 'seq': seq,
        'stepId': f'{MATCH}:sub:{topic}:key:{moment_id[3:]}', 'kind': 'subscription', 'topicId': topic,
        'trigger': {'type': 'keyEvent', 'ref': f'key:{moment_id[3:]}', 'reason': 'r', 'eventIds': [moment_id[3:]]},
        'matchTime': {'periodId': 1, 'timeMin': 0}, 'text': 'Chelsea score.', 'createdAt': f'2026-10-20T00:01:{seq:02d}Z',
        'timeSec': 30, 'eventSeq': event_seq, 'decision': {'score': 3, 'confidence': 0.9, 'clip': True}})


def follow_clip(topic, moment_id, event_seq, match_id=MATCH):
    """The engine's `FollowClip` message: Decision-1 judged the key moment worth a clip for the topic."""
    event = moment_id[3:]
    return EngineFollowClip.model_validate({
        'type': 'FollowClip', 'id': f'clip:{match_id}:{topic}:{event}', 'matchId': match_id, 'topicId': topic,
        'eventId': event, 'eventSeq': event_seq, 'stepId': f'{match_id}:sub:{topic}:key:{event}',
        'decision': {'score': 3, 'confidence': 0.9, 'clip': True}})


def timed_run(store):
    upstream = Upstream()
    upstream.add(MATCH, timed(), video=True)
    return Running(store, upstream=upstream)


def test_a_moment_judged_worth_a_clip_joins_the_follow_playlist_at_its_seq(store):
    with timed_run(store) as run:
        token, other = start(run.client)['session_token'], start(run.client, 'united-casual')['session_token']
        run.send(25)
        goal = next(m for m in view(run, token)['key_moments'] if m['kind'] == 'goal')
        topic = follow(run.client, token, TEAM).json()['follow']['topic_id']
        assert view(run, token)['follow_playlist'] is None
        assert deliver(run, clip_narrative(topic, goal['id'], 24))  # a narrative alone adds no clip
        assert view(run, token)['follow_playlist'] is None
        assert deliver(run, follow_clip(topic, goal['id'], 24))
        assert not deliver(run, follow_clip(topic, goal['id'], 24))  # a redelivery: one clip per topic and moment
        assert not deliver(run, follow_clip('topic:0000000000000bad', goal['id'], 24))  # unknown topic: ignored
        playlist = view(run, token)['follow_playlist']
        assert [c['captions'] for c in playlist['clips']] == [['Goal · Chelsea · Cole Palmer']]
        clip = playlist['clips'][0]
        assert clip['start'] < clip['marks'][0] <= clip['end'] and playlist['total_items'] == 1
        assert playlist['playlist'] and clip['playlist_start'] == clip['start']  # the match's own stream
        assert set(playlist['playback']) == {'transitions', 'slow_motion'}  # the reel's playback, as replies (037)
        assert 'observed_until' not in playlist  # steady between snapshots: the card is not rebuilt each tick
        assert view(run, other)['follow_playlist'] is None  # not following: no playlist
        purged = run.client.post('/admin/matches/purge', json={'match_id': MATCH}).json()['purged']
        assert purged['subscription_clips'] == 1


def test_a_clip_does_not_need_its_follow_narrative(store):
    """A narrative dropped as ungrounded never reaches the backend; its moment's clip still does."""
    with timed_run(store) as run:
        token = start(run.client)['session_token']
        run.send(25)
        goal = next(m for m in view(run, token)['key_moments'] if m['kind'] == 'goal')
        topic = follow(run.client, token, TEAM).json()['follow']['topic_id']
        assert deliver(run, follow_clip(topic, goal['id'], 24))
        assert view(run, token)['narratives'] == [] and len(view(run, token)['follow_playlist']['clips']) == 1


def test_a_follow_playlist_is_chronological_and_keeps_the_newest_max_items(store):
    with timed_run(store) as run:
        token = start(run.client)['session_token']
        run.send(25)
        moments = {m['kind']: m for m in view(run, token)['key_moments']}
        topic = follow(run.client, token, TEAM).json()['follow']['topic_id']
        assert deliver(run, follow_clip(topic, moments['goal']['id'], 24))  # delivered out of order
        assert deliver(run, follow_clip(topic, moments['red_card']['id'], 23))
        playlist = view(run, token)['follow_playlist']
        assert [c['source_ids'] for c in playlist['clips']] in (
            [[moments['red_card']['id']], [moments['goal']['id']]],
            [[moments['red_card']['id'], moments['goal']['id']]])  # merged when their windows overlap
        current = run.client.get('/dev/config/subscriptions').json()
        value = {**current['value'], 'clips': {**current['value']['clips'], 'max_items': 1}}
        assert run.client.put('/dev/config/subscriptions', json={'expected_revision': current['revision'],
                                                                 'value': value}).status_code == 200
        run.send(1)
        assert [c['source_ids'] for c in view(run, token)['follow_playlist']['clips']] == [[moments['goal']['id']]]


def test_follow_clips_stay_in_their_match(store):
    with Running(store, matches=(MATCH, OTHER)) as run:
        run.send(5)
        token = start(run.client)['session_token']
        topic = follow(run.client, token, TEAM).json()['follow']['topic_id']
        assert not deliver(run, follow_clip(topic, 'km:3', 1, match_id=OTHER))  # the topic is not the other match's
        assert view(run, token)['follow_playlist'] is None


def test_a_follow_clip_never_passes_the_snapshot(store):
    with timed_run(store) as run:
        token = start(run.client)['session_token']
        run.send(20)
        topic = follow(run.client, token, TEAM).json()['follow']['topic_id']
        # The goal (seq 24) is not in the snapshot yet: a clip judged at it waits for the viewer to reach it.
        moment = 'km:24'  # MA3 rows carry their seq as id in the double (benchmarks/doubles/spadl.py)
        assert deliver(run, follow_clip(topic, moment, 24))
        assert view(run, token)['follow_playlist'] is None
        run.send(5)
        assert len(view(run, token)['follow_playlist']['clips']) == 1


def moment_clip(moment_id, event_seq, buckets=('home:analytical',), match_id=MATCH):
    """The engine's `MomentClip`: a key event's clip on the shared narratives of its buckets (PLAN.md §10.2 D7)."""
    event = moment_id[3:]
    return EngineMomentClip.model_validate({
        'type': 'MomentClip', 'id': f'mclip:{match_id}:{event}', 'matchId': match_id, 'buckets': list(buckets),
        'eventId': event, 'eventSeq': event_seq, 'stepId': f'{match_id}:key:{event}'})


def test_key_event_clips_reach_every_insights_viewer_of_their_bucket(store):
    with timed_run(store) as run:
        token, other = start(run.client)['session_token'], start(run.client, 'united-casual')['session_token']
        run.send(25)
        goal = next(m for m in view(run, token)['key_moments'] if m['kind'] == 'goal')
        bucket = view(run, token)['bucket_id']
        assert view(run, token)['moment_playlist'] is None
        assert deliver(run, moment_clip(goal['id'], 24, (bucket,)))
        assert not deliver(run, moment_clip(goal['id'], 24, (bucket,)))  # a redelivery changes nothing
        assert not deliver(run, moment_clip(goal['id'], 24, (bucket,), match_id='gone-00000000'))  # unknown match
        playlist = view(run, token)['moment_playlist']
        assert [c['captions'] for c in playlist['clips']] == [['Goal · Chelsea · Cole Palmer']]
        card = playlist['clips'][0]['moments'][0]  # the preview card's facts
        assert (card['kind'], card['player_name'], card['team_name']) == ('goal', 'Cole Palmer', 'Chelsea')
        assert card['minute_label'] and card['score']
        assert set(playlist['playback']) == {'transitions', 'slow_motion'}
        if view(run, other)['bucket_id'] != bucket:
            assert view(run, other)['moment_playlist'] is None  # another bucket's shared narratives
        follow(run.client, token, TEAM)
        assert view(run, token)['moment_playlist'] is None  # a follower sees their story's clips instead
        purged = run.client.post('/admin/matches/purge', json={'match_id': MATCH}).json()['purged']
        assert purged['narrative_clips'] == 1


def test_a_key_event_clip_never_passes_the_snapshot(store):
    with timed_run(store) as run:
        token = start(run.client)['session_token']
        run.send(20)
        assert deliver(run, moment_clip('km:24', 24, (view(run, token)['bucket_id'],)))
        assert view(run, token)['moment_playlist'] is None
        run.send(5)
        assert len(view(run, token)['moment_playlist']['clips']) == 1


def test_one_follow_per_viewer_and_ownership(store):
    with Running(store, matches=(MATCH, OTHER)) as run:
        run.send(5)
        mine, theirs = start(run.client)['session_token'], start(run.client, 'neutral-simple')['session_token']
        first = follow(run.client, mine, TEAM)
        assert first.status_code == 200 and first.json()['created']
        again = follow(run.client, mine, {**TEAM, 'label': 'The Blues'})
        assert again.status_code == 200 and not again.json()['created']
        assert again.json()['follow']['subscription_id'] == first.json()['follow']['subscription_id']
        other = follow(run.client, mine, PLAYER)
        assert other.status_code == 409 and other.json()['code'] == 'follow_limit'
        subscription = first.json()['follow']['subscription_id']
        assert run.client.delete(path(theirs) + f'/follows/{subscription}').status_code == 404
        assert run.client.get(path(mine, OTHER) + '/follows').status_code == 404
        assert run.client.delete(path(mine) + f'/follows/{subscription}').status_code == 200
        assert follow(run.client, mine, PLAYER).status_code == 200
        listing = run.client.get(path(mine) + '/follows').json()
        assert listing['follow']['spec']['player_id'] == 'mbappe' and listing['follow']['spec']['team_id'] == 'madrid'
        assert len(listing['follows']) == 2 and listing['turns'] == []
        assert follow(run.client, theirs, {'kind': 'player', 'player_id': 'nobody', 'label': 'x'}).status_code == 422
        assert follow(run.client, theirs, {'kind': 'storyline', 'storyline_id': 'sl:x:9', 'label': 'x'}).status_code == 422
        assert follow(run.client, theirs, {'kind': 'theme', 'label': 'x'}).status_code == 422


def test_follow_changes_are_rate_limited_by_configuration(store):
    with Running(store) as run:
        run.send(5)
        token = start(run.client)['session_token']
        config = run.client.get('/dev/config/subscriptions').json()
        value = config['value']
        value['limits']['follow_changes_per_minute'] = 2
        assert run.client.put('/dev/config/subscriptions', json={'expected_revision': config['revision'],
                                                                 'value': value}).status_code == 200
        subscription = follow(run.client, token, TEAM).json()['follow']['subscription_id']
        assert run.client.delete(path(token) + f'/follows/{subscription}').status_code == 200
        response = follow(run.client, token, PLAYER)
        assert response.status_code == 429 and response.json()['code'] == 'rate_limited'


def test_engine_targets_share_topics_carry_buckets_and_revalidate(store):
    with Running(store) as run:
        run.send(5)
        url = f'/matches/{MATCH}/subscription-targets'
        empty = run.client.get(url)
        assert empty.status_code == 200 and empty.json()['topics'] == [] and empty.json()['revision'] == 0
        assert empty.json()['decision']['trigger_level'] == 2 and empty.json()['novelty']['enabled']
        assert empty.json()['limits']['min_minutes_between_narratives'] == 1
        assert 'Goal' in empty.json()['limits']['pivotal_key_types']
        # The engine refuses a document without its clip question (narrative-engine follows/topics.py).
        assert empty.json()['clips']['key_types'] and empty.json()['clips']['min_level'] == 3
        a, b = start(run.client)['session_token'], start(run.client, 'united-casual')['session_token']
        follow(run.client, a, TEAM)
        follow(run.client, b, {**TEAM, 'label': 'Blues'})
        body = run.client.get(url)
        topics = body.json()['topics']
        assert len(topics) == 1 and topics[0]['followers'] == 2
        assert topics[0]['buckets'] == ['away:casual', 'home:analytical'] and topics[0]['created_seq'] == 5
        assert topics[0]['spec']['label'] == 'Chelsea'  # the first follower's label names the topic
        assert run.client.get(url, headers={'If-None-Match': body.headers['etag']}).status_code == 304
        assert run.client.put(path(b) + '/audience', json={'bucket_id': 'neutral:simple'}).status_code == 200
        moved = run.client.get(url).json()
        assert moved['revision'] > body.json()['revision']
        assert moved['topics'][0]['buckets'] == ['home:analytical', 'neutral:simple']
        assert run.client.get('/matches/never-announced-00000000/subscription-targets').status_code == 404


def test_purge_removes_follows_topics_narratives_and_follow_chat(store):
    with Running(store, matches=(MATCH, OTHER), follow_model=Planner({'action': 'none', 'reply': 'Hello.'})) as run:
        run.send(5)
        run.send(5, match_id=OTHER)
        token, other = start(run.client)['session_token'], start(run.client, match_id=OTHER)['session_token']
        topic = follow(run.client, token, TEAM).json()['follow']['topic_id']
        follow(run.client, other, TEAM, OTHER)
        assert chat(run.client, token, 'hi')['status'] == 'answer'
        assert deliver(run, narrative(topic=topic))
        purged = run.client.post('/admin/matches/purge', json={'match_id': MATCH}).json()['purged']
        assert purged['subscriptions'] == 1 and purged['subscription_topics'] == 1
        assert purged['subscription_narratives'] == 1 and purged['subscription_revisions'] == 1
        assert purged['question_turns'] == 1
        with store.connect() as conn:
            left = {t: conn.execute(f'SELECT count(*) AS n FROM {t}').fetchone()['n']
                    for t in ('subscriptions', 'subscription_topics', 'subscription_narratives')}
        assert left == {'subscriptions': 1, 'subscription_topics': 1, 'subscription_narratives': 0}
        assert run.client.get(f'/matches/{OTHER}/subscription-targets').json()['topics'][0]['followers'] == 1


class Planner:
    """The follow chat's JSON model double: a fixed draft; records the system prompt it was given."""

    def __init__(self, draft):
        self.draft, self.systems = draft, []

    async def complete(self, system, payload, *, response_schema=None):
        self.systems.append(system)
        assert response_schema['json_schema']['name'] == 'follow_plan'
        return {'kind': None, 'subject': None, 'focus': '', 'label': None, **self.draft}


def chat(client, token, text, match_id=MATCH):
    response = client.post(path(token, match_id) + '/follow/messages', json={'prompt': text, 'request_id': str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()


def test_follow_chat_proposes_with_ids_resolved_by_rule(store):
    model = Planner({'action': 'follow', 'kind': 'player', 'subject': 'Mbappe', 'focus': 'his runs',
                     'reply': 'You can follow Mbappé.'})
    with Running(store, follow_model=model) as run:
        run.narratives.storylines[MATCH] = [STORYLINE]
        run.send(10)
        token = start(run.client)['session_token']
        reply = chat(run.client, token, 'I want to follow Mbappe')
        assert reply['status'] == 'proposal' and reply['proposal']['spec'] == {
            'kind': 'player', 'storyline_id': None, 'team_id': 'madrid', 'player_id': 'mbappe', 'focus': 'his runs',
            'label': 'Kylian Mbappé'}
        assert 'Madrid control the midfield' in model.systems[0] and 'Kylian Mbappé (Madrid)' in model.systems[0]
        assert view(run, token)['feed_mode'] == 'insights'  # a proposal is not a follow
        confirmed = follow(run.client, token, reply['proposal']['spec']).json()
        assert confirmed['follow']['topic_id'] == reply['proposal']['id']
        model.draft = {'action': 'follow', 'kind': 'storyline', 'subject': 'midfield control', 'reply': 'Sure.'}
        reply = chat(run.client, token, 'the midfield one')
        assert reply['proposal']['spec']['storyline_id'] == STORYLINE['id']
        model.draft = {'action': 'follow', 'kind': 'team', 'subject': 'Barcelona', 'reply': 'Sure.'}
        assert chat(run.client, token, 'Barcelona')['status'] == 'clarify'
        # A broad follow is proposed as asked: no breadth limit.
        model.draft = {'action': 'follow', 'kind': 'theme', 'focus': 'anything exciting', 'reply': 'Sure.'}
        assert chat(run.client, token, 'anything exciting')['proposal']['spec']['focus'] == 'anything exciting'
        turns = run.client.get(path(token) + '/follows').json()['turns']
        assert len(turns) == 4 and run.client.get(path(token)).json()['turns'] == []  # questions stay separate
        config = run.client.get('/dev/config/subscriptions').json()
        config['value']['limits']['planner_context_turns'] = 1  # the planner sees the latest turns only
        assert run.client.put('/dev/config/subscriptions', json={'expected_revision': config['revision'],
                                                                 'value': config['value']}).status_code == 200
        chat(run.client, token, 'one more')
        assert 'Viewer: anything exciting' in model.systems[-1] and 'Viewer: Barcelona' not in model.systems[-1]


def test_follow_chat_drills_in_with_resolved_choices_and_keeps_the_focus(store):
    # "Follow a story about Madrid's goals": the label keeps the focus; a clarification offers only choices that
    # resolve to something real (an unknown subject is dropped), never a widened team follow.
    model = Planner({'action': 'clarify', 'reply': 'Which angle?', 'options': [
        {'kind': 'team', 'subject': 'Madrid', 'focus': 'goals and chances', 'label': 'Madrid goals and chances'},
        {'kind': 'player', 'subject': 'Mbappe', 'focus': 'his finishing', 'label': 'Mbappé finishing'},
        {'kind': 'team', 'subject': 'Atlantis Rovers', 'focus': '', 'label': 'Atlantis'}]})
    with Running(store, follow_model=model) as run:
        run.send(10)
        token = start(run.client)['session_token']
        reply = chat(run.client, token, "follow a story about Madrid's goals")
        assert reply['status'] == 'clarify' and reply['proposal'] is None
        assert [(c['label'], c['spec']['kind'], c['spec']['focus']) for c in reply['candidates']] == [
            ('Madrid goals and chances', 'team', 'goals and chances'), ('Mbappé finishing', 'player', 'his finishing')]
        assert 'Matches being played now:' in model.systems[0]
        assert follow(run.client, token, reply['candidates'][0]['spec']).json()['follow']['label'] == \
            'Madrid goals and chances'


def test_follow_chat_needs_a_model_and_suggestions_do_not(store):
    with Running(store) as run:
        # The quiet one only becomes salient in extra time, which this viewer has not reached.
        rise = [{'at': {'periodId': 1, 'timeMin': 4}, 'salience': 0.1}, {'at': {'periodId': 4, 'timeMin': 115},
                                                                          'salience': 2.0}]
        run.narratives.storylines[MATCH] = [STORYLINE, {**STORYLINE, 'id': f'sl:{MATCH}:2', 'label': 'Quiet one',
                                                        'salienceHistory': rise}]
        run.send(25)
        token = start(run.client, 'united-casual')['session_token']
        response = run.client.post(path(token) + '/follow/messages', json={'prompt': 'hi', 'request_id': str(uuid4())})
        assert response.status_code == 503 and response.json()['code'] == 'model_unavailable'
        items = run.client.get(path(token) + '/follow/suggestions').json()['items']
        assert [i['label'] for i in items] == ['Madrid control the midfield', 'Cole Palmer', 'Levi Colwill', 'Madrid']
        follow(run.client, token, items[1]['spec'])
        assert 'Cole Palmer' not in [i['label'] for i in run.client.get(path(token) + '/follow/suggestions').json()['items']]


def test_storylines_are_bounded_by_the_snapshot(store):
    with Running(store) as run:
        later = {**STORYLINE, 'openedAt': {'periodId': 2, 'timeMin': 80}}
        run.narratives.storylines[MATCH] = [later]
        run.send(5)  # first-half events only
        token = start(run.client)['session_token']
        response = follow(run.client, token, {'kind': 'storyline', 'storyline_id': later['id'], 'label': 'x'})
        assert response.status_code == 422 and response.json()['code'] == 'unknown_storyline'


def test_key_moment_rules_follow_etl_key_events():
    spec = importlib.util.spec_from_file_location('m024', Path(__file__).parents[1] / 'migrations/024_subscriptions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = KeyMomentFeed.model_validate(module.CONFIG['key-moment-feed'])

    def row(i, type_id, team='chelsea', player='palmer', period=1, minute=10, quals=(), outcome=1, event_id=None):
        payload = {'eventId': event_id or i, 'eventSeq': i, 'outcome': outcome,
                   'qualifier': [{'qualifierId': q, **({'value': v} if v else {})} for q, v in quals]}
        return {'id': i, 'typeId': type_id, 'periodId': period, 'timeMin': minute, 'timeSec': 0, 'contestantId': team,
                'playerId': player, 'payload': json.dumps(payload)}

    rows = [row(1, 32, player=None, minute=0), row(2, 32, team='madrid', player=None, minute=0),
            row(3, 4, team='madrid', player='camavinga', quals=[(9, None)], outcome=0),
            row(4, 16, quals=[(9, None)], event_id=40), row(5, 900, quals=[(901, 'goal-overturned'), (55, '40')]),
            row(6, 17, team='madrid', player='camavinga', quals=[(32, None)]), row(7, 4, team='madrid', player='x'),
            row(8, 30, player=None, minute=46), row(9, 32, period=2, player=None, minute=45),
            row(10, 30, period=2, player=None, minute=95)]
    facts = [m for m in map(key_moment, rows) if m]
    teams = [{'id': 'chelsea', 'name': 'Chelsea'}, {'id': 'madrid', 'name': 'Madrid'}]
    players = [{'id': 'palmer', 'name': 'Cole Palmer'}, {'id': 'camavinga', 'name': 'Eduardo Camavinga'}]
    items = feed_moments(facts, config, teams, players)
    assert [(m['kind'], m['label']) for m in items] == [
        ('kick_off', 'Kick-off'), ('penalty', 'Penalty · Chelsea'), ('goal', 'Goal · Chelsea · Cole Palmer'),
        ('var_overturn', 'VAR · goal ruled out · Chelsea'), ('second_yellow', 'Second yellow · Eduardo Camavinga'),
        ('half_time', 'Half time · Chelsea 0–0 Madrid'), ('full_time', 'Full time · Chelsea 0–0 Madrid')]
    # second_half is not a configured kind; the overturned goal leaves the score at 0–0.
    assert next(m for m in items if m['kind'] == 'goal')['overturned']
    # A penalty's card names the side that won it, never the player who conceded it.
    penalty = next(m for m in items if m['kind'] == 'penalty')
    assert (penalty['team_name'], penalty['player_name'], penalty['score']) == ('Chelsea', None, 'Chelsea 0–0 Madrid')


def test_follow_chat_resolves_teams_by_their_etl_known_names():
    from backend.adapters.ma3 import team
    from backend.services.subscriptions import resolve
    teams = [team({'contestantId': 'che', 'position': 'home', 'name': 'Chelsea', 'shortName': None, 'code': 'CHE',
                   'knownNames': '["the Blues"]'}),
             team({'contestantId': 'mun', 'position': 'away', 'name': 'Manchester United', 'shortName': 'Man Utd',
                   'code': 'MUN', 'knownNames': '["United","the Red Devils"]'})]
    assert resolve('team', 'the Red Devils', teams, [], [], 0.5, 4) == ({'kind': 'team', 'team_id': 'mun',
                                                                      'label': 'Manchester United'}, [])
    assert resolve('team', 'Blues', teams, [], [], 0.5, 4)[0]['team_id'] == 'che'
    # "the" is in both teams' names: it weighs little, so "the Reds" is neither the Blues nor the Red Devils.
    assert resolve('team', 'the Reds', teams, [], [], 0.5, 4) == (None, [])
    assert team({'contestantId': 'x', 'position': 'home', 'name': 'X'})['known_names'] == []
