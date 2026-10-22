"""The match-data port (capture / stats / actions / cards / periods) over ETL GraphQL and this
service's own received events. A snapshot is (matchId, seq) with seq ≤ ETL's watermark, ≤ its SPADL
watermark (spadlSeq) and ≤ what this service received, so nothing past any of them is reachable."""
from collections import OrderedDict
from datetime import datetime, timezone

from backend.domain import RuleError
from backend.models.questions import MatchSnapshot, SnapshotInput
from . import ma3
from .etl_dab import EtlUnavailable

UNAVAILABLE = 'Live match data is temporarily unavailable. Please try again.'


class EtlDabMatchData:
    def __init__(self, dab, registry, *, cache=64):
        self.dab, self.registry, self.cache = dab, registry, cache
        self._stats, self._cards = OrderedDict(), OrderedDict()

    async def info(self, match):
        """ETL's match info (teams, players, capabilities); immutable, so read once."""
        if match.info is None:
            try:
                found = await self.dab.matches([match.match_id])
            except EtlUnavailable as exc:
                raise RuleError('snapshot_unavailable', UNAVAILABLE, 503) from exc
            if match.match_id not in found:
                raise RuleError('snapshot_unavailable', 'Match details are not available yet.', 503)
            match.info = found[match.match_id]
        return match.info

    async def played(self, match):
        """The last event both ETL (its watermark and SPADL watermark) and this service have committed, uncapped
        by any viewer: where another match stands. None before any, or while ETL is unavailable."""
        try:
            mark = (await self.dab.watermarks([match.match_id])).get(match.match_id, {'seq': 0})
        except EtlUnavailable:
            return None
        events = match.history(min(mark['seq'], mark.get('spadl_seq', 0)))
        return events[-1] if events else None

    async def capture(self, match, seq=None):
        """The newest snapshot both ETL and this service have committed, capped at `seq` when given
        (the snapshot a viewer's picture shows)."""
        info = await self.info(match)
        try:
            watermark = (await self.dab.watermarks([match.match_id])).get(match.match_id, {'seq': 0})
        except EtlUnavailable as exc:
            raise RuleError('snapshot_unavailable', UNAVAILABLE, 503) from exc
        # SPADL-derived data (actions, stats) exists only up to spadlSeq.
        bound = min(watermark['seq'], watermark.get('spadl_seq', 0), *(() if seq is None else (seq,)))
        async with match.lock:
            if match.purged:
                raise RuleError('match_not_found', 'This match is no longer available.', 404)
            events = match.history(bound)
        snapshot = MatchSnapshot.at(match.match_id, len(events), events[-1] if events else None,
                                    datetime.now(timezone.utc).isoformat())
        try:
            await match.sync_actions(self.dab, snapshot.seq)
        except EtlUnavailable as exc:
            raise RuleError('snapshot_unavailable', UNAVAILABLE, 503) from exc
        # Already-validated models: skip revalidating thousands per capture.
        return SnapshotInput.model_construct(snapshot=snapshot, events=events, actions=match.actions_at(snapshot.seq),
                                             teams=info['teams'], players=info['players'],
                                             data_reference=match.reference())

    async def stats(self, snapshot):
        rows = self._stats.get(snapshot.id)
        if rows is None:
            try:
                rows = await self.dab.stats_at_seq(snapshot.match_id, snapshot.seq)
            except EtlUnavailable as exc:
                raise RuleError('snapshot_unavailable', UNAVAILABLE, 503) from exc
            if not rows:
                raise RuleError('snapshot_unavailable', 'The match feed is catching up. Please try again.', 503)
            self._remember(self._stats, snapshot.id, rows)
        return {'snapshot_id': snapshot.id, 'match_id': snapshot.match_id, 'complete': True, 'stats': rows}

    async def actions(self, snapshot, *, offset=0, limit=100, start=None, end=None, actionType=None, playerId=None,
                      teamId=None, period=None, **unused):
        """SPADL actions at the snapshot, filtered and paged ([start, end) on the match clock)."""
        offset, limit = offset or 0, limit or 100
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError('Invalid page')
        types = None if actionType is None else ({actionType} if isinstance(actionType, str) else set(actionType))
        rows = [a.row() for a in self.registry.get(snapshot.match_id).actions_at(snapshot.seq)
                if (start is None or a.match_time_seconds >= start) and (end is None or a.match_time_seconds < end)
                and (types is None or a.action_type in types) and (playerId is None or a.player_id == playerId)
                and (teamId is None or a.team_id == teamId) and (period is None or a.period == period)]
        return {'snapshot_id': snapshot.id, 'match_id': snapshot.match_id, 'complete': True,
                'items': rows[offset:offset + limit], 'has_more': offset + limit < len(rows), 'total': len(rows)}

    async def cards(self, snapshot):
        """MA3 cards (outside SPADL) shown by the snapshot's seq, in order."""
        rows = self._cards.get(snapshot.id)
        if rows is None:
            try:
                rows = await self.dab.cards(snapshot.match_id, snapshot.seq)
            except EtlUnavailable as exc:
                raise RuleError('snapshot_unavailable', UNAVAILABLE, 503) from exc
            self._remember(self._cards, snapshot.id, rows)
        return rows

    async def facts(self, snapshot):
        """MA3 rows of the key-moment types (goals, cards, VAR, penalties, period markers) at the snapshot."""
        rows = self._cards.get(('facts', snapshot.id))
        if rows is None:
            try:
                rows = await self.dab.key_moment_rows(snapshot.match_id, snapshot.seq)
            except EtlUnavailable as exc:
                raise RuleError('snapshot_unavailable', UNAVAILABLE, 503) from exc
            self._remember(self._cards, ('facts', snapshot.id), rows)
        return rows

    async def score(self, snapshot, teams):
        """Goals per contestant at the snapshot from MA3 goals and VAR decisions (adapters/ma3.score)."""
        rows = [r for r in await self.facts(snapshot) if r['typeId'] in (ma3.GOAL, ma3.VAR)]
        return ma3.score(rows, teams)

    async def key_moments(self, snapshot):
        """Key-moment facts at the snapshot (adapters/ma3.key_moment), in match order."""
        found = [m for m in map(ma3.key_moment, await self.facts(snapshot)) if m]
        return sorted(found, key=lambda m: (m['period'], m['clock_seconds'], m['id']))

    async def periods(self, snapshot):
        """period -> (start video seconds, end video seconds or None) from received events up to the snapshot."""
        return periods(self.registry.get(snapshot.match_id).history(snapshot.seq))

    def _remember(self, cache, key, value):
        cache[key] = value
        while len(cache) > self.cache:
            cache.popitem(last=False)


def periods(events):
    found = {}
    for event in events:
        if event.deleted or event.video_seconds is None:
            continue
        if event.event_type == 'period_start':
            found[event.period] = (event.video_seconds, None)
        elif event.event_type == 'period_end' and event.period in found:
            found[event.period] = (found[event.period][0], event.video_seconds)
    return found
