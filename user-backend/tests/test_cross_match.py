"""Cross-match reach (PLAN.md §10.2 D5, D5b): questions, pins and follows about the demo's other live matches, each at
that match's own position and marked with its header; and the "Follow this story?" offer on answers."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.domain import RuleError
from backend.models.config import CONFIGS
from backend.services.cross_match import CrossMatch
from backend.services.names import coverage, rarity
from backend.services.product import ProductService, header_of, sources
from backend.services.questions import QuestionService
from benchmarks.doubles.config import SeededConfig, migration
from benchmarks.doubles.recording import FixtureEventSource
from harness import MATCH, Running, Upstream
from test_subscriptions import deliver, follow, narrative, path, start, view

OTHER = 'arsenal-liverpool-0badc0de'
# The second match: the same recording under other names (team ids stay; names are what viewers type).
RENAMES = {'Chelsea': 'Arsenal', 'Madrid': 'Liverpool', 'Kylian Mbappé': 'Mohamed Salah', 'Cole Palmer': 'Bukayo Saka',
           'Levi Colwill': 'William Saliba', 'Vinícius': 'Luis Díaz', 'Camavinga': 'Alexis Mac Allister',
           'Courtois': 'Alisson Becker'}


def other_source():
    text = (Path(__file__).parents[1] / 'fixtures/filter-lab.json').read_text(encoding='utf-8')
    for old, new in RENAMES.items():
        text = text.replace(old, new)
    return FixtureEventSource(content=text.encode(), filename='other.json')


def two_matches(store, **options):
    upstream = Upstream()
    upstream.add(MATCH)
    upstream.add(OTHER, other_source())
    return Running(store, matches=(MATCH, OTHER), upstream=upstream, **options)


def ask(run, token, prompt, seq=None):
    body = {'prompt': prompt, 'request_id': str(uuid4()), **({'seq': seq} if seq is not None else {})}
    response = run.client.post(path(token) + '/messages', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def refresh(run, match_id):
    async def go():
        await run.app.state.product.projection(match_id).refresh()
    run.client.portal.call(go)


def test_names_are_weighted_by_rarity_across_matches():
    entities = [('Manchester City', 'Man City', 'MCI'), ('Manchester United', 'Man Utd', 'MUN'),
                ('Tottenham Hotspur', 'Spurs', 'TOT'), ('Chelsea',)]
    weight = rarity(entities)
    assert coverage('what is the score in City v Spurs?', entities[2], weight) == 1.0  # a whole known name
    assert coverage('what is the score in City v Spurs?', entities[0], weight) >= 0.5  # its rare word
    assert coverage('what is the score in City v Spurs?', entities[1], weight) == 0.0
    assert coverage('how are the reds doing', entities[3], weight) == 0.0


def test_a_question_naming_another_match_is_answered_from_it_at_its_own_position(store):
    with two_matches(store) as run:
        run.send(20)
        run.send(9, match_id=OTHER)
        token = start(run.client)['session_token']
        reply = ask(run, token, 'How are Arsenal doing?', seq=3)
        assert reply['other_match']['id'] == OTHER
        assert [t['name'] for t in reply['other_match']['teams']] == ['Arsenal', 'Liverpool']
        assert all('score' not in t for t in reply['other_match']['teams'])
        # That match's own position (9 deliveries), never the viewer's seq (3) and never past it.
        assert reply['snapshot']['match_id'] == OTHER and reply['snapshot']['seq'] == 9
        own = ask(run, token, 'How is Cole Palmer doing?', seq=3)
        assert own['other_match'] is None and own['snapshot']['match_id'] == MATCH and own['snapshot']['seq'] == 3


def test_questions_see_the_live_matches_and_can_answer_what_else_is_on(store):
    """'What other games are on?' is answered from the live matches given as context, citing them; this match's
    minute is the viewer's picture, the other's its own played position."""
    from backend.models.questions import QuestionDraft
    seen = []

    class Agent:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            seen.append(context['live_matches'])
            other = next(m for m in context['live_matches'] if not m['this_match'])
            return QuestionDraft(answer_kind='match', status='answer', evidence_ids=[other['evidence_id']],
                                 text=f"{' v '.join(other['teams'])} is on, {other['minute']}'.")
    with two_matches(store, agent=Agent()) as run:
        run.send(20)
        run.send(9, match_id=OTHER)
        token = start(run.client)['session_token']
        reply = ask(run, token, 'what other games are playing right now', seq=3)
        here, other = seen[0]
        assert here['this_match'] and here['match_id'] == MATCH and not other['this_match']
        assert other['teams'] == ['Arsenal', 'Liverpool'] and other['minute'] is not None
        assert reply['status'] == 'answer' and reply['evidence'] == [
            {'id': f'match:{OTHER}', 'kind': 'match', 'label': 'Arsenal v Liverpool'}]


def test_cross_match_reach_is_off_in_config(store):
    with two_matches(store) as run:
        run.send(5)
        run.send(5, match_id=OTHER)
        current = run.client.get('/dev/config/cross-match').json()
        assert run.client.put('/dev/config/cross-match', json={
            'expected_revision': current['revision'], 'value': {**current['value'], 'enabled': False}}).status_code == 200
        token = start(run.client)['session_token']
        assert ask(run, token, 'How are Arsenal doing?')['other_match'] is None
        response = run.client.post(path(token) + '/follows', json={
            'spec': {'kind': 'team', 'team_id': 'madrid', 'label': 'Liverpool'}, 'match_id': OTHER})
        assert response.status_code == 404


def test_another_matchs_story_reaches_the_follow_view_marked_and_bounded_by_that_match(store):
    with two_matches(store) as run:
        run.send(20)
        run.send(9, match_id=OTHER)
        token = start(run.client)['session_token']
        suggestions = run.client.get(path(token) + '/follow/suggestions').json()['items']
        offered = [s for s in suggestions if s.get('match_id') == OTHER]
        assert offered and offered[0]['other_match']['id'] == OTHER
        response = run.client.post(path(token) + '/follows', json={
            'spec': {'kind': 'team', 'team_id': 'madrid', 'label': 'Liverpool'}, 'match_id': OTHER})
        assert response.status_code == 200, response.text
        followed = response.json()['follow']
        assert followed['match_id'] == OTHER and followed['bucket_id']
        targets = run.client.get(f'/matches/{OTHER}/subscription-targets').json()
        assert [t['topic_id'] for t in targets['topics']] == [followed['topic_id']]
        assert targets['topics'][0]['buckets'] == [followed['bucket_id']]  # that match's catalogue, not the viewer's
        assert run.client.get(f'/matches/{MATCH}/subscription-targets').json()['topics'] == []
        bucket = followed['bucket_id']
        assert deliver(run, narrative(OTHER, bucket, 1, 'Liverpool press.', followed['topic_id'], event_seq=8))
        assert deliver(run, narrative(OTHER, bucket, 2, 'Not played yet.', followed['topic_id'], event_seq=12))
        refresh(run, OTHER)
        snapshot = view(run, token)
        assert snapshot['feed_mode'] == 'following' and snapshot['follow_match']['id'] == OTHER
        assert [(n['text'], n['other_match']['id']) for n in snapshot['narratives']] == [('Liverpool press.', OTHER)]
        assert all('score' not in t for t in snapshot['follow_match']['teams'])
        # The other match moves on: this viewer's view follows it without this match changing.
        run.send(5, match_id=OTHER)
        refresh(run, OTHER)
        assert [n['text'] for n in view(run, token)['narratives']] == ['Liverpool press.', 'Not played yet.']
        # Unfollowing changes that match's targets; purging it ends the follow.
        assert run.client.post('/admin/matches/purge', json={'match_id': OTHER}).status_code == 200
        assert run.client.get(path(token) + '/follows').json()['follow'] is None
        # A follow whose checks passed before the purge is 404 at the insert, never a follow without its topic.
        with pytest.raises(RuleError) as raised:
            run.app.state.product.subscriptions.follow(token, OTHER, followed['spec'], followed['topic_id'], 9, None,
                                                       100, bucket)
        assert raised.value.status == 404
        assert run.client.get(path(token) + '/follows').json()['follows'] == []


def test_a_pinned_stat_from_another_match_shows_its_value_there_marked():
    shared = {'match': {'id': OTHER, 'fixture': 'arsenal-liverpool',
                        'teams': [{'id': 'arsenal', 'name': 'Arsenal', 'score': 2}, {'id': 'liverpool', 'name': 'Liverpool'}]},
              'stats': [{'id': 'arsenal:shots', 'label': 'Arsenal shots', 'value': 7, 'available': True}],
              'calculations': {}}
    product = ProductService.__new__(ProductService)
    product.projections = {OTHER: SimpleNamespace(shared=shared)}
    offer = {'kind': 'standard', 'standard_stat_id': 'arsenal:shots', 'label': 'Arsenal shots'}
    card = product.cross_card(f'standard:arsenal:shots@{OTHER}', offer)
    assert card['value'] == 7 and card['pinned'] and card['id'] == f'standard:arsenal:shots@{OTHER}'
    assert card['other_match'] == header_of(shared['match']) and 'score' not in card['other_match']['teams'][0]
    product.projections = {}
    gone = product.cross_card(f'standard:arsenal:shots@{OTHER}', offer)
    assert gone['available'] is False and 'other_match' not in gone
    assert sources({'offers': [{'calculation_id': f'standard:x@{OTHER}'}, {'calculation_id': 'standard:y'}],
                    'follow': {'match_id': 'third'}}, MATCH) == {OTHER, 'third'}


class Decide:
    def __init__(self, probability):
        self.probability_value, self.calls = probability, 0

    async def probability(self, state, instructions, true, false, timeout):
        self.calls += 1
        if isinstance(self.probability_value, Exception):
            raise self.probability_value
        return self.probability_value


def offer(decide, draft, offers=(), config=None):
    service = QuestionService.__new__(QuestionService)
    service.decide, service.config = decide, config or SeededConfig()
    from backend.adapters.decision import Window
    service._offers = Window()
    return asyncio.run(service._follow_offer('How is Saka getting on?', draft, list(offers), None))


def test_a_story_question_gets_one_follow_offer_and_stats_never_do():
    story = SimpleNamespace(status='answer', answer_kind='match', text='Saka keeps beating his man.')
    assert offer(Decide(0.9), story) == {'prompt': 'How is Saka getting on?', 'other_match': None}
    assert offer(Decide(0.2), story) is None
    stat = SimpleNamespace(status='answer', answer_kind='statistic', text='7 shots.')
    decide = Decide(0.99)
    assert offer(decide, stat) is None and decide.calls == 0
    assert offer(decide, story, offers=[{'id': 'o'}]) is None and decide.calls == 0
    assert offer(Decide(RuntimeError('down')), story) is None  # optional: the answer never fails with it
    unsupported = SimpleNamespace(status='unsupported', answer_kind='match', text='No.')
    assert offer(Decide(0.99), unsupported) == {'prompt': 'How is Saka getting on?', 'other_match': None}
    clarify = SimpleNamespace(status='clarification', answer_kind='match', text='Which Saka?')
    assert offer(Decide(0.99), clarify) is None


def test_follow_offers_are_paced_by_config():
    story = SimpleNamespace(status='answer', answer_kind='match', text='t')
    seeded = CONFIGS['follow-offer'].model_validate({**migration('040_cross_match').OFFER, 'max_per_minute': 1})
    config = SimpleNamespace(get=lambda name: asyncio.sleep(0, seeded))
    service = QuestionService.__new__(QuestionService)
    from backend.adapters.decision import Window
    service.decide, service.config, service._offers = Decide(0.9), config, Window()
    first = asyncio.run(service._follow_offer('q', story, [], None))
    second = asyncio.run(service._follow_offer('q', story, [], None))
    assert first and second is None and service.decide.calls == 1


def test_another_match_is_named_only_above_the_configured_share_and_above_this_match():
    def match(match_id, teams, players=()):
        return SimpleNamespace(match_id=match_id, fixture=match_id, purged=False,
                               info={'teams': [{'id': t, 'name': t} for t in teams],
                                     'players': [{'id': p, 'name': p} for p in players]})
    here = match('here', ['Chelsea', 'Manchester United'], ['Cole Palmer'])
    city = match('city', ['Manchester City', 'Tottenham Hotspur'], ['Erling Haaland'])
    registry = SimpleNamespace(matches={'here': here, 'city': city})

    async def info(m):
        return m.info
    cross = CrossMatch(registry, SimpleNamespace(info=info), SeededConfig())
    named = lambda text: asyncio.run(cross.named(here, text))
    assert named('Is Haaland scoring?')[0] is city
    assert named('How is Tottenham doing?')[0] is city
    assert named('How is Cole Palmer doing?') is None
    assert named('What about Manchester?') is None  # shared by both matches: this one is not outscored


def test_the_follow_chat_finds_a_name_in_another_match_when_this_one_has_none():
    from backend.services.subscriptions import SubscriptionService
    city = SimpleNamespace(match_id='city', fixture='mancity-tottenham', purged=False)
    teams = [{'id': 'mancity', 'name': 'Manchester City', 'short_name': 'Man City', 'known_names': ['City']},
             {'id': 'tottenham', 'name': 'Tottenham Hotspur', 'short_name': 'Spurs'}]

    class Cross:
        async def settings(self):
            return SimpleNamespace(enabled=True)

        def others(self, match_id):
            return [city]

    service = SubscriptionService.__new__(SubscriptionService)
    service.cross = Cross()

    async def context(match_id, seq=None):
        return None, teams, [], []

    async def info(match):
        return {'teams': teams, 'players': []}
    service._context, service.match_data = context, SimpleNamespace(info=info)
    draft = SimpleNamespace(kind='team', subject="City's pressing")
    found = asyncio.run(service._elsewhere('here', draft, SimpleNamespace(min_name_match=0.5)))
    assert found['team_id'] == 'mancity' and found['match_id'] == 'city' and found['other_match']['id'] == 'city'
    option = SubscriptionService._option('here', {**found, 'label': 'City'})
    assert option['match_id'] == 'city' and option['spec']['team_id'] == 'mancity'
    assert option['id'] != SubscriptionService._option('here', {'kind': 'team', 'team_id': 'mancity', 'label': 'City'})['id']


def test_the_follow_planner_sees_the_other_matches_teams_and_squads():
    from backend.services.subscriptions import SubscriptionService
    city = SimpleNamespace(match_id='city', fixture='mancity-tottenham', purged=False)
    info = {'teams': [{'id': 'mancity', 'name': 'Manchester City'}],
            'players': [{'id': 'haaland', 'name': 'Erling Haaland', 'team_id': 'mancity'}]}

    class Cross:
        async def settings(self):
            return SimpleNamespace(enabled=True)

        def others(self, match_id):
            return [city]

        async def info_of(self, match):
            return info
    service = SubscriptionService.__new__(SubscriptionService)
    service.cross = Cross()
    assert asyncio.run(service._other_entities('here')) == (info['teams'], info['players'])


def test_purging_another_match_sends_its_followers_back_to_insights():
    from backend.services.live_viewers import LiveViewers
    live = LiveViewers()
    follower = live.attach('a', {'follow': {'match_id': OTHER}, 'offers': []})
    bystander = live.attach('b', {'follow': None, 'offers': []})
    here = SimpleNamespace(live=live, match=SimpleNamespace(match_id=MATCH, changed=asyncio.Event()))
    product = ProductService.__new__(ProductService)
    product.projections, product.audiences = {MATCH: here}, SimpleNamespace(forget=lambda ids: None)
    asyncio.run(product._purged([OTHER]))
    assert follower.viewer['follow'] is None and here.match.changed.is_set()
    assert bystander.viewer == {'follow': None, 'offers': []}


def test_the_follow_chat_picks_the_match_whose_name_fits_best_not_the_first_that_matches():
    from backend.services.subscriptions import SubscriptionService
    united = SimpleNamespace(match_id='utd', fixture='chelsea-united', purged=False)
    city = SimpleNamespace(match_id='city', fixture='mancity-tottenham', purged=False)
    teams = {'utd': [{'id': 'chelsea', 'name': 'Chelsea'}, {'id': 'manutd', 'name': 'Manchester United'}],
             'city': [{'id': 'mancity', 'name': 'Manchester City'}, {'id': 'tottenham', 'name': 'Tottenham Hotspur'}]}

    class Cross:
        async def settings(self):
            return SimpleNamespace(enabled=True)

        def others(self, match_id):
            return [united, city]  # the shared word "Manchester" matches in the first one too

    service = SubscriptionService.__new__(SubscriptionService)
    service.cross = Cross()

    async def context(match_id, seq=None):
        return None, teams[match_id], [], []

    async def info(match):
        return {'teams': teams[match.match_id], 'players': []}
    service._context, service.match_data = context, SimpleNamespace(info=info)
    draft = SimpleNamespace(kind='team', subject='Manchester City')
    found = asyncio.run(service._elsewhere('here', draft, SimpleNamespace(min_name_match=0.3)))
    assert found['team_id'] == 'mancity' and found['match_id'] == 'city'
