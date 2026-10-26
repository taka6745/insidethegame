"""ETL GraphQL (Data API builder) reads: matches, watermarks, the stat catalogue at a seq, SPADL actions
and MA3 card rows up to a seq, and canonical events for gap recovery.

Allowlisted queries only (local/README.md Contracts §3); the model never supplies query text. Never
another service's database."""
import asyncio
import json

import httpx

from backend.models.events import Event
from backend.adapters import ma3

MATCH_FIELDS = '''matchId fixture sourceMatchId runId status scheduledKickoff synthetic description capabilities
  teams { items { contestantId position name shortName code knownNames primaryColour secondaryColour crestAssetId } }
  players { items { playerId contestantId name shirtNumber position starter } }'''
MATCHES = 'query ($ids: [String!]) { matches(filter: {matchId: {in: $ids}}) { items { %s } } }' % MATCH_FIELDS
ALL_MATCHES = 'query ($after: String) { matches(first: 100, after: $after) { items { %s } hasNextPage endCursor } }' % MATCH_FIELDS
WATERMARKS = '''query ($ids: [String!]) { matchWatermarks(filter: {matchId: {in: $ids}}) {
  items { matchId seq spadlSeq periodId clockSeconds videoSeconds eventTime } } }'''
STATS = '''query ($m: String!, $s: Int!) { executeStatsAtSeq(matchId: $m, seq: $s) {
  statId kind contestantId label value available unit definition eventTypes complete } }'''
# Served trend indicators (multi-minute measures such as field tilt), plain labels and meanings, as of seq.
TRENDS = '''query ($m: String!, $s: Int!) { executeTrendsAtSeq(matchId: $m, seq: $s) {
  trendId label meaning unit contestantId window minutes value enabled } }'''
# Final SPADL actions a snapshot may read (local/README.md Contracts §3), paged in action order.
ACTIONS = '''query ($m: String!, $from: Int!, $s: Int!, $after: String) { spadlActions(
  filter: {matchId: {eq: $m}, finalSeq: {gt: $from, lte: $s}}, orderBy: {actionId: ASC}, first: 1000, after: $after) {
  items { actionId periodId teamId playerId typeName resultName bodypartName bodypartObserved startX startY endX endY
          startZone endZone seq finalSeq sourceEventId sourceTypeId clockSeconds videoSeconds possessionId
          fromShotOffTarget defensiveBlock }
  hasNextPage endCursor } }'''
# MA3 rows of some Opta types (17 cards, 16 goals, 900 VAR) up to a snapshot: outside SPADL. The database
# bounds them by the indexed eventSeq column (the canonical seq each row derives from).
RAW = '''query ($m: String!, $types: [Int!], $s: Int!, $after: String) { rawEvents(
  filter: {matchId: {eq: $m}, typeId: {in: $types}, eventSeq: {lte: $s}}, orderBy: {seq: ASC}, first: 100, after: $after) { items { id typeId periodId timeMin timeSec contestantId playerId payload }
  hasNextPage endCursor } }'''
MAX_PAGES = 50  # 50,000 actions; a match has about 3,000.
# ETL DAB's canonicalEvents entity (dbo.canonicalEvents columns, etl/dab/dab-config.json).
CANONICAL = '''query ($m: String!, $s: Int!) { canonicalEvents(filter: {matchId: {eq: $m}, seq: {eq: $s}}) {
  items { seq eventId revision eventType teamId playerId bodyPart periodId matchTimeSeconds outcome distanceMetres
          deleted videoSeconds x y possessionId qualifiers } } }'''


class EtlUnavailable(RuntimeError):
    """ETL GraphQL failed or returned errors; callers retry."""


class EtlDab:
    def __init__(self, url, *, transport=None, timeout=10):
        self.url, self.transport, self.timeout = url, transport, timeout
        self._http, self._loop = None, None

    def _client(self):
        """One pooled client per event loop: projections read on every committed event."""
        loop = asyncio.get_running_loop()
        if self._http is None or self._loop is not loop:
            self._http, self._loop = httpx.AsyncClient(timeout=self.timeout, transport=self.transport), loop
        return self._http

    async def aclose(self):
        if self._http is not None and self._loop is asyncio.get_running_loop():
            await self._http.aclose()
        self._http = self._loop = None

    async def _post(self, query, variables):
        try:
            response = await self._client().post(self.url, json={'query': query, 'variables': variables})
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EtlUnavailable('ETL GraphQL is unavailable') from exc
        if body.get('errors') or not isinstance(body.get('data'), dict):
            raise EtlUnavailable('ETL GraphQL returned errors')
        return body['data']

    async def matches(self, ids=None):
        """Match info by matchId (all matches when ids is None); purged matches have no rows."""
        if ids is not None:
            if not ids:
                return {}
            data = await self._post(MATCHES, {'ids': list(ids)})
            return {row['matchId']: ma3.match(row) for row in data['matches']['items']}
        found, after = {}, None
        while True:
            page = (await self._post(ALL_MATCHES, {'after': after}))['matches']
            found.update((row['matchId'], ma3.match(row)) for row in page['items'])
            if not page.get('hasNextPage'):
                return found
            after = page['endCursor']

    async def watermarks(self, ids):
        """matchId → latest committed canonical seq and its clock; no row means seq 0."""
        if not ids:
            return {}
        data = await self._post(WATERMARKS, {'ids': list(ids)})
        return {row['matchId']: {'seq': row['seq'], 'spadl_seq': row.get('spadlSeq') or 0, 'period': row.get('periodId'),
                                 'clock_seconds': row.get('clockSeconds'), 'video_seconds': row.get('videoSeconds')}
                for row in data['matchWatermarks']['items']}

    async def canonical_event(self, match_id, seq):
        """ETL's stored MatchEvent at (match_id, seq) for gap recovery; None when ETL is past seq but
        has no valid row. Raises EtlUnavailable while ETL cannot answer or has not reached seq."""
        items = (await self._post(CANONICAL, {'m': match_id, 's': seq}))['canonicalEvents']['items']
        if not items:
            # ETL may simply lag: only a watermark past seq means it has no row.
            if (await self.watermarks([match_id])).get(match_id, {'seq': 0})['seq'] < seq:
                raise EtlUnavailable(f'ETL has not reached seq {seq}')
            return None
        row = items[0]
        try:
            return Event.model_validate_json(json.dumps({
                'event_id': row['eventId'], 'match_id': match_id, 'revision': row['revision'],
                'event_type': row['eventType'], 'team_id': row.get('teamId'), 'player_id': row.get('playerId'),
                'body_part': row.get('bodyPart'), 'period': row['periodId'], 'match_time_seconds': row['matchTimeSeconds'],
                'outcome': row.get('outcome'), 'distance_metres': row.get('distanceMetres'), 'deleted': bool(row['deleted']),
                'sequence': seq, 'video_seconds': row.get('videoSeconds'), 'x': row.get('x'), 'y': row.get('y'),
                'possession_id': row.get('possessionId'), 'qualifiers': json.loads(row.get('qualifiers') or '{}')}))
        except (KeyError, ValueError):
            return None  # ETL holds it too, but not as a valid canonical event.

    async def spadl_actions(self, match_id, after_seq, seq):
        """DAB spadlActions rows with after_seq < finalSeq <= seq, in actionId order. Call only with
        seq <= the watermark's spadlSeq: every such row is then stored."""
        rows, after = [], None
        for _ in range(MAX_PAGES):
            page = (await self._post(ACTIONS, {'m': match_id, 'from': after_seq, 's': seq, 'after': after}))['spadlActions']
            rows += page['items']
            if not page.get('hasNextPage'):
                return rows
            after = page['endCursor']
        raise EtlUnavailable('Too many SPADL actions for one read')

    async def raw_events(self, match_id, types, seq):
        """MA3 rows (rawEvents) of the given Opta types with eventSeq <= seq, in MA3 seq order."""
        rows, after = [], None
        for _ in range(MAX_PAGES):
            page = (await self._post(RAW, {'m': match_id, 'types': list(types), 's': seq, 'after': after}))['rawEvents']
            rows += page['items']
            if not page.get('hasNextPage'):
                return rows
            after = page['endCursor']
        raise EtlUnavailable('Too many MA3 rows')

    async def cards(self, match_id, seq):
        """MA3 cards up to seq (adapters/ma3.card)."""
        return [ma3.card(row) for row in await self.raw_events(match_id, [ma3.CARD], seq)]

    async def key_moment_rows(self, match_id, seq):
        """MA3 rows of the key-moment types up to seq (adapters/ma3.key_moment, ma3.score)."""
        return await self.raw_events(match_id, ma3.KEY_MOMENT_TYPES, seq)

    async def trends_at_seq(self, match_id, seq):
        """Enabled trend indicators as of (match_id, seq): ETL's values, so an answer never computes its own."""
        data = await self._post(TRENDS, {'m': match_id, 's': seq})
        return [row for row in data['executeTrendsAtSeq'] or [] if row.get('enabled', True)]

    async def stats_at_seq(self, match_id, seq):
        """The catalogue as of (match_id, seq); an empty list means not yet committed (retry)."""
        data = await self._post(STATS, {'m': match_id, 's': seq})
        return [ma3.stat(row) for row in data['executeStatsAtSeq'] or []]
