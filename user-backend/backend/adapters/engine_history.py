"""Live narrative history for questions and replays: the narrative engine's GraphQL summaries
(recaps), the snapshot's SPADL actions (tails) and its goals, penalties and MA3 cards (key events and
key moments). Neither holds anything the match has not streamed; reads are bounded to the snapshot."""
import httpx

from backend.models.actions import SHOT_FAMILY
from backend.models.events import minute_label
from backend.services.question_tools import compact_action

PERIOD_START = {1: 0, 2: 45, 3: 90, 4: 105, 5: 120}
TIERS = ('minute', 'five-minute', 'twenty-minute', 'half')  # The engine's contextBlocks `tier`.
QUERY = '''query ($m: String!) { contextBlocks(matchId: $m) {
  id tier summary supersededBy coversFrom { periodId timeMin } coversTo { periodId timeMin } } }'''

STORYLINES = '''query ($m: String!) { storylines(matchId: $m) {
  id label team status outcome keyEventIds salienceHistory { at { periodId timeMin } salience } openedAt { periodId timeMin } updatedAt { periodId timeMin }
  resolvedAt { periodId timeMin } resolutions { at { periodId timeMin } outcome }
  beats { at { periodId timeMin } headline } } }'''


def reached(at, snapshot):
    """A storyline clock (an analysis of a closed minute) the snapshot has passed."""
    return at is not None and snapshot.clock_seconds is not None and \
        (at['periodId'], (at['timeMin'] + 1) * 60) <= (snapshot.period or 1, snapshot.clock_seconds)


class EngineHistoryData:
    audience_dependent = False

    def __init__(self, url, match_data, config, *, transport=None, timeout=10):
        self.url, self.match_data, self.config = url, match_data, config  # config: services/config.ConfigService
        self.transport, self.timeout = transport, timeout

    async def capture(self, payload, *, purpose='question'):
        return  # The engine has no snapshot handshake; match facts are pinned through ETL.

    async def _post(self, query, variables):
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.post(self.url, json={'query': query, 'variables': variables})
            response.raise_for_status()
            body = response.json()
        if body.get('errors'):
            raise ValueError('Narrative history is unavailable')
        return body['data']

    async def _blocks(self, snapshot):
        """Every summary of this match ending at or before the snapshot, as recap rows."""
        if snapshot.clock_seconds is None:
            return []
        data = await self._post(QUERY, {'m': snapshot.match_id})
        rows = []
        for block in data['contextBlocks'] or []:
            if block.get('tier') not in TIERS:
                continue  # A tier this service does not offer viewers.
            start, end = block['coversFrom'], block['coversTo']
            period = start['periodId']
            row = {'id': 'recap:' + block['id'], 'match_id': snapshot.match_id, 'period': period, 'tier': block['tier'],
                   'start_seconds': start['timeMin'] * 60, 'end_seconds': (end['timeMin'] + 1) * 60,
                   'summary': block['summary'], 'superseded_by': block['supersededBy'] and 'recap:' + block['supersededBy'],
                   'label': minute_label(period, start['timeMin'] * 60) if block['tier'] == 'minute' else
                            f"{minute_label(period, start['timeMin'] * 60)}–{minute_label(period, end['timeMin'] * 60)}"}
            if (period, row['end_seconds']) <= (snapshot.period or 1, snapshot.clock_seconds):
                rows.append(row)
        # A block superseded by one that ends after the snapshot is still current at the snapshot.
        shown = {r['id'] for r in rows}
        rows = [{**r, 'superseded_by': r['superseded_by'] if r['superseded_by'] in shown else None} for r in rows]
        return sorted(rows, key=lambda r: (r['period'], r['start_seconds'], -r['end_seconds']))

    async def _actions(self, snapshot):
        rows, offset = [], 0
        while True:
            page = await self.match_data.actions(snapshot, offset=offset, limit=1000)
            rows += page['items']
            offset += len(page['items'])
            if not page.get('has_more') or not page['items']:
                return rows

    async def key_events(self, snapshot):
        """Goals (incl. own goals), penalties and cards at the snapshot, in clock order."""
        actions = [compact_action(a) for a in await self._actions(snapshot) if key_kind(a)]
        cards = await self.match_data.cards(snapshot)
        return sorted([*actions, *cards], key=lambda e: (e['period'], e['match_time_seconds']))

    async def compact(self, snapshot):
        archive, actions = await self._blocks(snapshot), await self._actions(snapshot)
        blocks = [row for row in archive if row['superseded_by'] is None]
        period = snapshot.period or 1
        end = max((r['end_seconds'] for r in blocks if r['period'] == period), default=PERIOD_START.get(period, 0) * 60)
        return {'snapshot_id': snapshot.id, 'match_id': snapshot.match_id, 'complete': True, 'synthetic': True,
                'blocks': blocks, 'coverage_end_seconds': end,
                'tail': [compact_action(a) for a in actions if (a['period'], a['match_time_seconds']) >= (period, end)],
                'key_events': await self.key_events(snapshot), 'available_tiers': list(TIERS)}

    async def recaps(self, snapshot, ids=None, start=None, end=None, tier=None, offset=0, limit=30, period=None, **unused):
        rows = [r for r in await self._blocks(snapshot) if (not ids or r['id'] in ids) and (not tier or r['tier'] == tier)
                and (period is None or r['period'] == period)
                and (start is None or r['end_seconds'] > start) and (end is None or r['start_seconds'] < end)]
        return {'snapshot_id': snapshot.id, 'match_id': snapshot.match_id, 'complete': True,
                'items': rows[offset:offset + limit], 'has_more': offset + limit < len(rows)}

    async def key_moments(self, snapshot, period=None, limit=100):
        """Goals, dismissals, penalties and cards at the snapshot, ranked; facts, not authored copy."""
        ranks, replay = await self.config.get('key-moment-ranks'), await self.config.get('replay-timing')
        found = [e for e in await self.key_events(snapshot)
                 if e.get('video_seconds') is not None and (period is None or e['period'] == period)]
        found.sort(key=lambda e: (ranks.rank(key_kind(e)), e['video_seconds']))
        items = []
        for rank, e in enumerate(found[:limit], 1):
            kind = key_kind(e)
            what = (f"{e['colour'].replace('_', ' ')} card" if kind in ('card', 'dismissal') else
                    'own goal' if e.get('result') == 'owngoal' else kind)
            label = minute_label(e['period'], e['match_time_seconds'])
            # The same windows as clips of that action type (cards: their own timing key).
            before, after = replay.timing.get('card' if 'colour' in e else e['action_type'], replay.default)
            if kind == 'goal':
                before, after = replay.timing.get('goal', (before, after))
            items.append({'id': 'moment:' + e['id'], 'rank': rank, 'period': e['period'], 'label': label,
                          'title': f"{label} {what}", 'summary': None,
                          'event_ids': [e['id']], 'start_video_seconds': max(0.0, e['video_seconds'] - before),
                          'end_video_seconds': e['video_seconds'] + after})
        return {'snapshot_id': snapshot.id, 'match_id': snapshot.match_id, 'complete': True,
                'items': sorted(items, key=lambda m: (m['period'], m['start_video_seconds'])), 'has_more': False}

    async def storylines(self, snapshot):
        """The match's storylines as the snapshot knew them: opened by then, beats up to then, and a storyline
        resolved later still active (status is resolved or active only), and salience as of the last analysis the
        snapshot has passed."""
        data = await self._post(STORYLINES, {'m': snapshot.match_id})
        rows = []
        for line in data['storylines'] or []:
            if not reached(line['openedAt'], snapshot):
                continue
            # Only resolution has a clock; a later active/dormant change is not the snapshot's to see. A storyline
            # that reopened is resolved between a resolution and the first beat after it.
            ends = [*(line.get('resolutions') or []),
                    *([{'at': line['resolvedAt'], 'outcome': line['outcome']}] if line['resolvedAt'] else [])]
            end = next((r for r in reversed(ends) if reached(r['at'], snapshot)), None)
            when = lambda at: (at['periodId'], at['timeMin'])
            resolved = end is not None and not any(when(b['at']) > when(end['at']) and reached(b['at'], snapshot)
                                                   for b in line['beats'])
            rows.append({'id': line['id'], 'label': line['label'], 'team_id': line['team'],
                         'status': 'resolved' if resolved else 'active',
                         'salience': next((h['salience'] for h in reversed(line['salienceHistory'])
                                          if reached(h['at'], snapshot)), 0.0),
                         'outcome': end['outcome'] if resolved else None,
                         'beats': [b['headline'] for b in line['beats'] if reached(b['at'], snapshot)]})
        return rows

    async def read(self, snapshot, operation, **filters):
        if operation == 'compact':
            return await self.compact(snapshot)
        if operation == 'key_moments':
            return await self.key_moments(snapshot, filters.get('period'), filters.get('limit') or 100)
        if operation in ('recaps', 'tier_recaps'):
            return await self.recaps(snapshot, **filters)
        if operation == 'minute_recaps':
            return await self.recaps(snapshot, **{**filters, 'tier': 'minute'})
        raise ValueError('Unsupported narrative read')


def key_kind(row):
    """goal | penalty | dismissal | card for a key event (action or MA3 card row), else None."""
    if 'colour' in row:
        return 'dismissal' if row['colour'] in ('red', 'second_yellow') else 'card'
    if row.get('result') == 'owngoal' or (row.get('action_type') in SHOT_FAMILY and row.get('result') == 'success'):
        return 'goal'
    return 'penalty' if row.get('action_type') == 'shot_penalty' else None
