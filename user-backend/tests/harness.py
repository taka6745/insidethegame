"""Test doubles for the backend's upstreams, following local/README.md Contracts exactly.

`Upstream` plays the external feed (Event Hubs messages through the real parsing path) and
ETL's Data API builder GraphQL (an httpx transport answering the contract's queries from
the events it has committed). `Narratives` answers the engine's contextBlocks query."""
import json
import re
from collections import Counter
from pathlib import Path
from uuid import uuid4

import httpx

from backend.adapters.etl_dab import EtlDab
from backend.adapters.match_stream import handle_match_message
from backend.app import create_app
from backend.services.observed import observed
from benchmarks.doubles.recording import FixtureEventSource
from benchmarks.doubles.spadl import actions_from_events, page, raw_from_events

ROOT = Path(__file__).resolve().parents[1]
MATCH = 'riverton-madrid-1a2b3c4d'
KINDS = [('goals', ('goal',)), ('shots', ('shot', 'goal')), ('passes', ('pass',)), ('corners', ('corner',)),
         ('cards', ('card',)), ('tackles', ('tackle',))]


def camel(name):
    return re.sub(r'_([a-z])', lambda m: m.group(1).upper(), name)


def reference_stats(events, teams, capabilities):
    """An independent count of the catalogue's simple kinds (ETL owns the real projection)."""
    rows, latest = [], observed(events)
    supported = set((capabilities or {}).get('supported_event_types') or
                    ('pass', 'shot', 'goal', 'corner', 'card', 'tackle'))
    for team in [None, *teams]:
        scope = team['id'] if team else 'all'
        counts = Counter(e.event_type for e in latest if team is None or e.team_id == team['id'])
        for kind, types in KINDS:
            available = set(types) <= supported
            rows.append({'statId': f'{scope}:{kind}', 'kind': kind, 'contestantId': team and team['id'],
                         'label': f"{team['name'] if team else 'Both teams'} {kind}",
                         'value': sum(counts[t] for t in types) if available else None, 'available': available,
                         'unit': '', 'definition': f'Observed {", ".join(types)} events.',
                         'eventTypes': json.dumps(types), 'complete': True})
        for kind in ('possession', 'pass_accuracy'):
            rows.append({'statId': f'{scope}:{kind}', 'kind': kind, 'contestantId': team and team['id'],
                         'label': f"{team['name'] if team else 'Both teams'} {kind.replace('_', ' ')}",
                         'value': None, 'available': False, 'unit': '%', 'definition': 'Not in this test feed.',
                         'eventTypes': '[]', 'complete': True})
    return rows


class FeedMatch:
    def __init__(self, match_id, source, fixture, *, video=False):
        self.match_id, self.source, self.fixture, self.video = match_id, source, fixture, video
        self.sent = self.committed = 0
        self.status = 'scheduled'

    def event(self, seq):
        return self.source.events[seq - 1].model_copy(update={'match_id': self.match_id, 'sequence': seq})

    def events(self, seq):
        return [self.event(s) for s in range(1, seq + 1)]

    @property
    def home(self):
        return self.source.spec['teams'][0]['id']

    def actions(self):
        """ETL's SPADL rows for the whole recording (a row exists once committed past its finalSeq)."""
        if not hasattr(self, '_actions'):
            self._actions = actions_from_events(self.source.events, self.home)
            self._raw = raw_from_events(self.source.events)
        return self._actions

    def row(self):
        teams = [{'contestantId': t['id'], 'position': ('home', 'away')[i], 'name': t['name'],
                  'shortName': t['name'], 'code': t['name'][:3].upper(), 'primaryColour': '#001c68',
                  'secondaryColour': '#ffffff', 'crestAssetId': t['id']} for i, t in enumerate(self.source.spec['teams'])]
        players = [{'playerId': p['id'], 'contestantId': p['team_id'], 'name': p['name'], 'shirtNumber': i + 1,
                    'position': 'FW', 'starter': True} for i, p in enumerate(self.source.spec['players'])]
        # A recording without capabilities declares the complete test contract explicitly; undeclared means unknown.
        capabilities = {camel(k): v for k, v in self.source.capabilities.items()}
        capabilities['eventTypes'] = capabilities.pop('supportedEventTypes', None)
        capabilities['video'] = self.video
        return {'matchId': self.match_id, 'fixture': self.fixture, 'sourceMatchId': self.source.match_id,
                'runId': str(uuid4()), 'status': self.status, 'scheduledKickoff': '2026-10-20T15:00:00.000Z',
                'synthetic': True, 'description': ' v '.join(t['name'] for t in self.source.spec['teams']),
                'capabilities': json.dumps(capabilities), 'teams': {'items': teams}, 'players': {'items': players}}


class Upstream:
    """The external feed and ETL GraphQL for any number of matches."""

    def __init__(self):
        self.matches = {}
        self.calls = Counter()
        self.canonical = False  # Whether DAB exposes canonicalEvents.
        self.spadl_lag = 0  # How many seqs ETL's SPADL watermark trails its seq watermark.
        self.trends = []  # executeTrendsAtSeq rows served for every match and seq.
        self.trend_seqs = []  # the seq each trend read asked for
        self.canonical_missing = set()  # Seqs ETL holds no canonical row for.
        self.transport = httpx.MockTransport(self._graphql)
        self.dab = EtlDab('http://etl-dab/graphql', transport=self.transport)

    def add(self, match_id=MATCH, source=None, fixture=None, *, video=False):
        self.matches[match_id] = FeedMatch(match_id, source or FixtureEventSource(), fixture or match_id.rsplit('-', 1)[0],
                                           video=video)
        return self.matches[match_id]

    async def kickoff(self, registry, match_id=MATCH, *, sent_at='2099-01-01T00:00:00Z'):
        match = self.matches[match_id]
        ma1 = {'feed': 'MA1', 'schemaVersion': 1, 'matchId': match_id, 'synthetic': True, 'fixture': match.fixture,
               'sourceMatchId': match.source.match_id, 'runId': str(uuid4()), 'timeStamp': sent_at,
               'scheduledKickoff': sent_at, 'contestant': [], 'provenance': 'SYNTHETIC test feed'}
        await handle_match_message(json.dumps(ma1), ('0', 1), registry)

    async def send(self, registry, match_id=MATCH, count=1, *, commit=True):
        """The next `count` canonical events, each before its MA3 row; ETL commits them unless told not to."""
        match = self.matches[match_id]
        for _ in range(count):
            if match.sent >= len(match.source.events):
                break
            match.sent += 1
            envelope = {'type': 'MatchEvent', 'version': 2, 'matchId': match_id, 'seq': match.sent,
                        'timeStamp': '2026-10-20T15:00:00.000Z', 'synthetic': True,
                        'event': match.event(match.sent).model_dump(mode='json')}
            await handle_match_message(json.dumps(envelope), ('0', match.sent + 1), registry)
            await handle_match_message(json.dumps({'feed': 'MA3', 'matchId': match_id, 'eventSeq': match.sent}), None, registry)
            match.status = 'live'
        if commit:
            match.committed = match.sent

    def _graphql(self, request):
        body = json.loads(request.content)
        query, variables = body['query'], body.get('variables') or {}
        if 'executeStatsAtSeq' in query:
            self.calls['stats'] += 1
            match = self.matches.get(variables['m'])
            if match is None or variables['s'] > match.committed:
                return httpx.Response(200, json={'data': {'executeStatsAtSeq': []}})
            teams = match.source.spec['teams']
            rows = reference_stats(match.events(variables['s']), teams, match.source.spec.get('capabilities'))
            return httpx.Response(200, json={'data': {'executeStatsAtSeq': rows}})
        if 'executeTrendsAtSeq' in query:
            self.trend_seqs.append(variables['s'])
            return httpx.Response(200, json={'data': {'executeTrendsAtSeq': self.trends}})
        if 'spadlActions' in query:
            self.calls['actions'] += 1
            match = self.matches.get(variables['m'])
            rows = [] if match is None else [r for r in match.actions() if variables['from'] < r['finalSeq'] <= min(
                variables['s'], match.committed)]
            items, more, cursor = page(rows, variables.get('after'), 1000)
            return httpx.Response(200, json={'data': {'spadlActions': {'items': items, 'hasNextPage': more,
                                                                       'endCursor': cursor}}})
        if 'rawEvents' in query:
            match = self.matches.get(variables['m'])
            rows = [] if match is None else [r for r in (match.actions(), match._raw)[1] if r['typeId'] in variables['types']
                                             and r.get('eventSeq') is not None and r['eventSeq'] <= variables['s']]
            items, more, cursor = page(rows, variables.get('after'), 100)
            return httpx.Response(200, json={'data': {'rawEvents': {'items': items, 'hasNextPage': more,
                                                                    'endCursor': cursor}}})
        if 'matchWatermarks' in query:
            self.calls['watermarks'] += 1
            items = []
            for match_id in variables['ids']:
                match = self.matches.get(match_id)
                if match and match.committed:
                    event = match.event(match.committed)
                    items.append({'matchId': match_id, 'seq': match.committed, 'spadlSeq': max(0, match.committed - self.spadl_lag),
                                  'periodId': event.period,
                                  'clockSeconds': event.match_time_seconds, 'videoSeconds': event.video_seconds,
                                  'eventTime': '2026-10-20T15:00:00.000Z'})
            return httpx.Response(200, json={'data': {'matchWatermarks': {'items': items}}})
        if 'canonicalEvents' in query:
            # Gap recovery; ETL's DAB serves this only where the entity is exposed.
            match = self.matches.get(variables['m'])
            if not self.canonical:
                return httpx.Response(200, json={'errors': [{'message': 'Unknown field canonicalEvents'}]})
            items = []
            if match and variables['s'] <= len(match.source.events) and variables['s'] not in self.canonical_missing:
                e = match.event(variables['s'])
                items.append({'seq': variables['s'], 'eventId': e.event_id, 'revision': e.revision, 'eventType': e.event_type,
                              'teamId': e.team_id, 'playerId': e.player_id, 'bodyPart': e.body_part, 'periodId': e.period,
                              'matchTimeSeconds': e.match_time_seconds, 'outcome': e.outcome,
                              'distanceMetres': e.distance_metres, 'deleted': e.deleted, 'videoSeconds': e.video_seconds,
                              'x': e.x, 'y': e.y, 'possessionId': e.possession_id, 'qualifiers': json.dumps(e.qualifiers)})
            return httpx.Response(200, json={'data': {'canonicalEvents': {'items': items}}})
        if 'matches' in query:
            self.calls['matches'] += 1
            ids = variables.get('ids')
            items = [m.row() for i, m in self.matches.items() if ids is None or i in ids]
            return httpx.Response(200, json={'data': {'matches': {'items': items, 'hasNextPage': False, 'endCursor': None}}})
        return httpx.Response(200, json={'errors': [{'message': 'Unknown query'}]})


class Narratives:
    """The engine's contextBlocks (each with a `tier`) and storylines per match."""

    def __init__(self):
        self.blocks, self.storylines = {}, {}
        self.queried = []
        self.transport = httpx.MockTransport(self._graphql)

    def _graphql(self, request):
        body = json.loads(request.content)
        variables = body['variables']
        self.queried.append(variables['m'])
        if 'storylines(' in body['query']:
            return httpx.Response(200, json={'data': {'storylines': self.storylines.get(variables['m'], [])}})
        return httpx.Response(200, json={'data': {'contextBlocks': self.blocks.get(variables['m'], [])}})


def build(store, *, upstream=None, agent=None, planner=None, narratives=None, media=None, **options):
    """The real app over test doubles. Returns (app, upstream, narrative double)."""
    upstream = upstream or Upstream()
    narratives = narratives or Narratives()
    app = create_app(store, upstream.dab, narrative_url='http://engine/graphql', narrative_transport=narratives.transport,
                     agent=agent, planner=planner, media=media, enable_dev_feed=True, enable_lab=True, **options)
    return app, upstream, narratives


def session(client, match_id=MATCH, profile='riverton-analytical'):
    response = client.post(f'/lab/matches/{match_id}/chat/sessions', json={'profile_id': profile})
    assert response.status_code == 200, response.text
    return response.json()['session_token']


def ask(client, token, prompt, request_id=None, match_id=MATCH):
    return client.post(f'/lab/matches/{match_id}/chat/{token}/messages',
                       json={'prompt': prompt, 'request_id': request_id or str(uuid4())})


def fixture_planner():
    from backend.agents.workflow import RuleWorkflow
    from benchmarks.doubles.agents import FixtureCodingAgent, FixtureGoalAgent
    return RuleWorkflow(FixtureGoalAgent(), FixtureCodingAgent(), source='fixture')


def fixture_agent():
    from benchmarks.doubles.question_agent import FixtureQuestionAgent
    return FixtureQuestionAgent()


class Running:
    """A started app over doubles: `with Running(store) as run: run.send(10)`."""

    def __init__(self, store, *, agent='fixture', planner='fixture', matches=(MATCH,), upstream=None, **options):
        agent = fixture_agent() if agent == 'fixture' else agent
        planner = fixture_planner() if planner == 'fixture' else planner
        self.app, self.upstream, self.narratives = build(store, agent=agent, planner=planner, upstream=upstream, **options)
        self.matches = matches

    def __enter__(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app).__enter__()
        self.registry = self.app.state.registry
        for match_id in self.matches:
            if match_id not in self.upstream.matches:
                self.upstream.add(match_id)
            self.client.portal.call(self.upstream.kickoff, self.registry, match_id)
        return self

    def __exit__(self, *exc):
        self.client.__exit__(*exc)

    def send(self, count=1, match_id=MATCH, commit=True):
        self.client.portal.call(lambda: self.upstream.send(self.registry, match_id, count, commit=commit))

    @property
    def service(self):
        return self.app.state.questions

    def match(self, match_id=MATCH):
        return self.registry.get(match_id)


def timed(source=None):
    """The same recording with a video timeline (30 s per delivery), so replays can cut clips."""
    spec = json.loads((source or FixtureEventSource()).content)
    spec['events'] = [{**e, 'videoSeconds': 30.0 * index} for index, e in enumerate(spec['events'])]
    return FixtureEventSource(content=json.dumps(spec).encode())
