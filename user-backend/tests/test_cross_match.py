"""Cross-match reach: questions, pins and follows about the other live matches, each at
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
from support import deliver, follow_narrative, path, start, view

OTHER = 'redcastle-portalbion-0badc0de'
# The second match: the same recording under other names (team ids stay; names are what viewers type).
RENAMES = {'Riverton Rovers': 'Redcastle Town', 'Madrid': 'Port Albion', 'Kylian Mbappé': 'Idris Rowntree', 'Kai Ashworth': 'Marcus Ellingham',
           'Matteo Rivas': 'Samuel Achterberg', 'Vinícius': 'Luis Díaz', 'Camavinga': 'Alexis Mac Allister',
           'Courtois': 'Gareth Holloway'}


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
    entities = [('Skybridge City', 'Skybridge', 'SKC'), ('Forgeham United', 'Forgeham', 'FGU'),
                ('Whitmore Wanderers', 'Whitmore', 'WHW'), ('Riverton Rovers',)]
    weight = rarity(entities)
    assert coverage('what is the score in City v Whitmore?', entities[2], weight) == 1.0  # a whole known name
    assert coverage('what is the score in City v Whitmore?', entities[0], weight) >= 0.5  # its rare word
    assert coverage('what is the score in City v Whitmore?', entities[1], weight) == 0.0
    assert coverage('how are the mariners doing', entities[3], weight) == 0.0


def test_a_question_naming_another_match_is_answered_from_it_at_its_own_position(store):
    with two_matches(store) as run:
        run.send(20)
        run.send(9, match_id=OTHER)
        token = start(run.client)['session_token']
        reply = ask(run, token, 'How are Redcastle Town doing?', seq=3)
        assert reply['other_match']['id'] == OTHER
        assert [t['name'] for t in reply['other_match']['teams']] == ['Redcastle Town', 'Port Albion']
        assert all('score' not in t for t in reply['other_match']['teams'])
        # That match's own position (9 deliveries), never the viewer's seq (3) and never past it.
        assert reply['snapshot']['match_id'] == OTHER and reply['snapshot']['seq'] == 9
        own = ask(run, token, 'How is Kai Ashworth doing?', seq=3)
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
        assert other['teams'] == ['Redcastle Town', 'Port Albion'] and other['minute'] is not None
        assert reply['status'] == 'answer' and reply['evidence'] == [
            {'id': f'match:{OTHER}', 'kind': 'match', 'label': 'Redcastle Town v Port Albion'}]


def test_a_request_about_both_games_is_answered_from_each_at_its_own_position(store):
    """'Show me the goals from both games': one answer per match, each at that match's position, the
    other marked with its header; never narrowed to one match."""
    from backend.models.questions import QuestionDraft

    class Agent:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            if not context.get('single_match'):
                return QuestionDraft(answer_kind='match', status='answer', text='From each match.',
                                     per_match=[m['match_id'] for m in context['live_matches']])
            # A part answers for its match alone: the other matches are not in its sight.
            assert [m['match_id'] for m in context['live_matches']] == [context['snapshot']['match_id']]
            return QuestionDraft(answer_kind='match', status='answer', text=f"At {context['snapshot']['seq']}.")
    with two_matches(store, agent=Agent()) as run:
        run.send(20)
        run.send(9, match_id=OTHER)
        token = start(run.client)['session_token']
        reply = ask(run, token, 'show me the goals from both games', seq=3)
        here, other = reply['parts']
        assert (here['snapshot']['match_id'], here['snapshot']['seq'], here['other_match']) == (MATCH, 3, None)
        assert (other['snapshot']['match_id'], other['snapshot']['seq']) == (OTHER, 9)
        assert other['other_match']['id'] == OTHER and reply['follow_offer'] is None
        # One receipt for the whole answer: the parts' model calls are in it, not shown again per part.
        assert here['usage'] is None and other['usage'] is None and reply['usage'] is not None


def test_a_trend_question_sees_etls_served_value_and_can_cite_it(store):
    """Field tilt is a served trend; the answer gets ETL's value as evidence, never its own sum."""
    from backend.models.questions import QuestionDraft
    seen = []

    class Agent:
        mode = 'fixture'

        async def answer(self, prompt, context, tools):
            seen.append(context['trends'])
            tilt = context['trends'][0]
            return QuestionDraft(answer_kind='match', status='answer', evidence_ids=['trend:field_tilt:riverton:last5'],
                                 text=f"{tilt['label']}: {tilt['values']['riverton']['last5']}.")
    with two_matches(store, agent=Agent()) as run:
        run.upstream.trends = [{'trendId': 'field_tilt', 'label': 'share of final-third play', 'meaning': 'm',
                                'unit': 'share', 'contestantId': 'riverton', 'window': 'last5', 'minutes': 5,
                                'value': 0.62, 'enabled': True},
                               {'trendId': 'momentum', 'label': 'momentum', 'meaning': 'm', 'unit': 'index',
                                'contestantId': 'riverton', 'window': 'last5', 'minutes': 5, 'value': 1.0, 'enabled': False}]
        run.send(20)
        token = start(run.client)['session_token']
        reply = ask(run, token, 'what is the field tilt?', seq=12)
        assert reply['snapshot']['seq'] == 12
        assert [t['label'] for t in seen[0]] == ['share of final-third play']  # disabled trends never shown
        assert reply['evidence'][0]['kind'] == 'trend' and reply['evidence'][0]['value'] == 0.62
        assert reply['evidence'][0]['label'] == 'share of final-third play (Riverton Rovers, last 5 minutes)'  # words, not ids
        # Bounded at the viewer's snapshot: ETL is asked as of the answer's seq, never its newest.
        assert run.upstream.trend_seqs and set(run.upstream.trend_seqs) == {reply['snapshot']['seq']}


def test_cross_match_reach_is_off_in_config(store):
    with two_matches(store) as run:
        run.send(5)
        run.send(5, match_id=OTHER)
        current = run.client.get('/dev/config/cross-match').json()
        assert run.client.put('/dev/config/cross-match', json={
            'expected_revision': current['revision'], 'value': {**current['value'], 'enabled': False}}).status_code == 200
        token = start(run.client)['session_token']
        assert ask(run, token, 'How are Redcastle Town doing?')['other_match'] is None
        response = run.client.post(path(token) + '/follows', json={
            'spec': {'kind': 'team', 'team_id': 'madrid', 'label': 'Port Albion'}, 'match_id': OTHER})
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
            'spec': {'kind': 'team', 'team_id': 'madrid', 'label': 'Port Albion'}, 'match_id': OTHER})
        assert response.status_code == 200, response.text
        followed = response.json()['follow']
        assert followed['match_id'] == OTHER and followed['bucket_id']
        targets = run.client.get(f'/matches/{OTHER}/subscription-targets').json()
        assert [t['topic_id'] for t in targets['topics']] == [followed['topic_id']]
        assert targets['topics'][0]['buckets'] == [followed['bucket_id']]  # that match's catalogue, not the viewer's
        assert run.client.get(f'/matches/{MATCH}/subscription-targets').json()['topics'] == []
        bucket = followed['bucket_id']
        assert deliver(run, follow_narrative(OTHER, bucket, 1, 'Port Albion press.', followed['topic_id'], event_seq=8))
        assert deliver(run, follow_narrative(OTHER, bucket, 2, 'Not played yet.', followed['topic_id'], event_seq=12))
        refresh(run, OTHER)
        snapshot = view(run, token)
        assert snapshot['feed_mode'] == 'following' and snapshot['follow_match']['id'] == OTHER
        assert [(n['text'], n['other_match']['id']) for n in snapshot['narratives']] == [('Port Albion press.', OTHER)]
        assert all('score' not in t for t in snapshot['follow_match']['teams'])
        # The other match moves on: this viewer's view follows it without this match changing.
        run.send(5, match_id=OTHER)
        refresh(run, OTHER)
        assert [n['text'] for n in view(run, token)['narratives']] == ['Port Albion press.', 'Not played yet.']
        # Unfollowing changes that match's targets; purging it ends the follow.
        assert run.client.post('/admin/matches/purge', json={'match_id': OTHER}).status_code == 200
        assert run.client.get(path(token) + '/follows').json()['follow'] is None
        # A follow whose checks passed before the purge is 404 at the insert, never a follow without its topic.
        with pytest.raises(RuleError) as raised:
            run.app.state.product.subscriptions.follow(token, OTHER, followed['spec'], followed['topic_id'], 9, None,
                                                       100, bucket)
        assert raised.value.status == 404
        assert run.client.get(path(token) + '/follows').json()['follows'] == []


def test_purging_the_viewers_match_ends_its_follow_of_another_match_with_a_new_revision(store):
    with two_matches(store) as run:
        run.send(20)
        run.send(9, match_id=OTHER)
        token = start(run.client)['session_token']
        response = run.client.post(path(token) + '/follows', json={
            'spec': {'kind': 'team', 'team_id': 'madrid', 'label': 'Port Albion'}, 'match_id': OTHER})
        assert response.status_code == 200, response.text
        before = run.client.get(f'/matches/{OTHER}/subscription-targets')
        assert before.json()['topics']
        assert run.client.post('/admin/matches/purge', json={'match_id': MATCH}).status_code == 200
        # The engine re-reads targets only on a new revision: an unchanged one would keep the orphaned topic alive.
        after = run.client.get(f'/matches/{OTHER}/subscription-targets',
                               headers={'If-None-Match': before.headers['etag']})
        assert after.status_code == 200 and after.json()['topics'] == []
        assert after.json()['revision'] != before.json()['revision']


def test_a_pinned_stat_from_another_match_shows_its_value_there_marked():
    shared = {'match': {'id': OTHER, 'fixture': 'redcastle-portalbion',
                        'teams': [{'id': 'redcastle', 'name': 'Redcastle Town', 'score': 2}, {'id': 'portalbion', 'name': 'Port Albion'}]},
              'stats': [{'id': 'redcastle:shots', 'label': 'Redcastle Town shots', 'value': 7, 'available': True}],
              'calculations': {}}
    product = ProductService.__new__(ProductService)
    product.projections = {OTHER: SimpleNamespace(shared=shared)}
    offer = {'kind': 'standard', 'standard_stat_id': 'redcastle:shots', 'label': 'Redcastle Town shots'}
    card = product.cross_card(f'standard:redcastle:shots@{OTHER}', offer)
    assert card['value'] == 7 and card['pinned'] and card['id'] == f'standard:redcastle:shots@{OTHER}'
    assert card['other_match'] == header_of(shared['match']) and 'score' not in card['other_match']['teams'][0]
    product.projections = {}
    gone = product.cross_card(f'standard:redcastle:shots@{OTHER}', offer)
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
    return asyncio.run(service._follow_offer('How is Ellingham getting on?', draft, list(offers), None))


def test_a_story_question_gets_one_follow_offer_and_stats_never_do():
    story = SimpleNamespace(status='answer', answer_kind='match', text='Ellingham keeps beating his man.')
    assert offer(Decide(0.9), story) == {'prompt': 'How is Ellingham getting on?', 'other_match': None}
    assert offer(Decide(0.2), story) is None
    stat = SimpleNamespace(status='answer', answer_kind='statistic', text='7 shots.')
    decide = Decide(0.99)
    assert offer(decide, stat) is None and decide.calls == 0
    assert offer(decide, story, offers=[{'id': 'o'}]) is None and decide.calls == 0
    assert offer(Decide(RuntimeError('down')), story) is None  # optional: the answer never fails with it
    unsupported = SimpleNamespace(status='unsupported', answer_kind='match', text='No.')
    assert offer(Decide(0.99), unsupported) == {'prompt': 'How is Ellingham getting on?', 'other_match': None}
    clarify = SimpleNamespace(status='clarification', answer_kind='match', text='Which Ellingham?')
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
    here = match('here', ['Riverton Rovers', 'Forgeham United'], ['Kai Ashworth'])
    city = match('city', ['Forgeham City', 'Whitmore Wanderers'], ['Gustav Edlund'])  # shares "Forgeham"
    registry = SimpleNamespace(matches={'here': here, 'city': city})

    async def info(m):
        return m.info
    cross = CrossMatch(registry, SimpleNamespace(info=info), SeededConfig())
    named = lambda text: asyncio.run(cross.named(here, text))
    assert named('Is Edlund scoring?')[0] is city
    assert named('How is Whitmore doing?')[0] is city
    assert named('How is Kai Ashworth doing?') is None
    assert named('What about Forgeham?') is None  # shared by both matches: this one is not outscored


def test_the_follow_chat_finds_a_name_in_another_match_when_this_one_has_none():
    from backend.services.subscriptions import SubscriptionService
    city = SimpleNamespace(match_id='city', fixture='skybridge-whitmore', purged=False)
    teams = [{'id': 'skybridge', 'name': 'Skybridge City', 'short_name': 'Skybridge', 'known_names': ['City']},
             {'id': 'whitmore', 'name': 'Whitmore Wanderers', 'short_name': 'Whitmore'}]

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
    assert found['team_id'] == 'skybridge' and found['match_id'] == 'city' and found['other_match']['id'] == 'city'
    option = SubscriptionService._option('here', {**found, 'label': 'City'})
    assert option['match_id'] == 'city' and option['spec']['team_id'] == 'skybridge'
    assert option['id'] != SubscriptionService._option('here', {'kind': 'team', 'team_id': 'skybridge', 'label': 'City'})['id']


def test_the_follow_planner_sees_the_other_matches_teams_and_squads():
    from backend.services.subscriptions import SubscriptionService
    city = SimpleNamespace(match_id='city', fixture='skybridge-whitmore', purged=False)
    info = {'teams': [{'id': 'skybridge', 'name': 'Skybridge City'}],
            'players': [{'id': 'edlund', 'name': 'Gustav Edlund', 'team_id': 'skybridge'}]}

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
    united = SimpleNamespace(match_id='utd', fixture='riverton-forgeham', purged=False)
    city = SimpleNamespace(match_id='city', fixture='skybridge-whitmore', purged=False)
    teams = {'utd': [{'id': 'riverton', 'name': 'Skybridge Rovers'}, {'id': 'forgeham', 'name': 'Forgeham United'}],
             'city': [{'id': 'skybridge', 'name': 'Skybridge City'}, {'id': 'whitmore', 'name': 'Whitmore Wanderers'}]}

    class Cross:
        async def settings(self):
            return SimpleNamespace(enabled=True)

        def others(self, match_id):
            return [united, city]  # the shared word "Skybridge" matches in the first one too

    service = SubscriptionService.__new__(SubscriptionService)
    service.cross = Cross()

    async def context(match_id, seq=None):
        return None, teams[match_id], [], []

    async def info(match):
        return {'teams': teams[match.match_id], 'players': []}
    service._context, service.match_data = context, SimpleNamespace(info=info)
    draft = SimpleNamespace(kind='team', subject='Skybridge City')
    found = asyncio.run(service._elsewhere('here', draft, SimpleNamespace(min_name_match=0.3)))
    assert found['team_id'] == 'skybridge' and found['match_id'] == 'city'


def test_another_match_stands_where_etl_has_it_with_stoppage_minutes_and_its_score():
    """The listing reads another match at ETL's watermarks, not its newest delivery, labels stoppage 45+N′ and
    carries each match's score at that position (this one's at the viewer's snapshot)."""
    here, other = SimpleNamespace(match_id='here', purged=False), SimpleNamespace(match_id='other', purged=False)
    played = SimpleNamespace(match_id='other', seq=40, period=1, clock_seconds=46 * 60 + 10)  # 47th minute
    viewer = SimpleNamespace(match_id='here', seq=7, period=1, clock_seconds=600)
    goals = {('here', 7): {'here-a': 0, 'here-b': 2}, ('other', 40): {'other-a': 1}}

    async def info(match):
        return {'teams': [{'id': f'{match.match_id}-a', 'name': f'{match.match_id} A'},
                          {'id': f'{match.match_id}-b', 'name': f'{match.match_id} B'}]}

    async def at_etl(match):
        return played

    async def score(snapshot, teams):
        return goals[(snapshot.match_id, snapshot.seq)]

    async def settings():
        return SimpleNamespace(enabled=True)
    cross = CrossMatch(SimpleNamespace(matches={'here': here, 'other': other}),
                       SimpleNamespace(info=info, played=at_etl, score=score), None)
    cross.settings = settings
    rows = asyncio.run(cross.listing(here, viewer))
    assert [(r['match_id'], r['minute'], r['score']) for r in rows] == [('here', '11′', [0, 2]),
                                                                       ('other', '45+2′', [1, 0])]


def test_the_follow_planner_is_told_each_live_matchs_score_and_minute():
    """The live-match listing in the planner's prompt carries each match's score."""
    from backend.agents.subscription_planner import SubscriptionPlanner
    seen = {}

    class Model:
        async def complete(self, system, payload, response_schema=None):
            seen['system'] = system
            return {'action': 'none', 'kind': None, 'subject': None, 'focus': '', 'label': '', 'options': [],
                    'reply': 'ok'}

    class Prompts:
        async def template(self, role):
            return 'Matches being played now:\n{live_matches}'
    live = [{'match_id': 'a', 'this_match': True, 'teams': ['Redcastle Town', 'Port Albion'], 'minute': '30′',
             'score': [0, 0]},
            {'match_id': 'b', 'this_match': False, 'teams': ['Skybridge City', 'Whitmore Wanderers'], 'minute': '69′',
             'score': [1, 1]},
            {'match_id': 'c', 'this_match': False, 'teams': ['Riverton Rovers', 'Forgeham United'], 'minute': None,
             'score': None}]
    asyncio.run(SubscriptionPlanner(Model(), Prompts()).plan('follow Whitmore', teams=[], players=[], storylines=[],
                                                             follow=None, turns=[], live_matches=live))
    assert seen['system'].splitlines()[1:] == ['- Redcastle Town 0–0 Port Albion (30′) (this match)',
                                               '- Skybridge City 1–1 Whitmore Wanderers (69′)',
                                               '- Riverton Rovers v Forgeham United']
