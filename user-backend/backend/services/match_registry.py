"""Every match this service knows (its MA1 arrived), one LiveMatch each; purge per match."""
import asyncio
import logging
import time

from backend.domain import RuleError
from backend.services.live_match import LiveMatch

log = logging.getLogger(__name__)


GAP_BATCH = 500  # missing seqs filled per recovery pass once the first has timed out


class MatchRegistry:
    def __init__(self, repository, *, max_calculations=10_000, dab=None):
        if isinstance(max_calculations, bool) or not isinstance(max_calculations, int) or not 1 <= max_calculations <= 1_000_000:
            raise ValueError('FILTER_MAX_CALCULATIONS must be an integer between 1 and 1000000')
        self.repository, self.max_calculations = repository, max_calculations
        self.dab = dab  # ETL GraphQL: custom calculations read SPADL actions through it.
        self.matches = {}
        self.on_purge = []  # async callbacks(match_ids) after a purge commits
        self.on_match = []  # callbacks(LiveMatch) when a match becomes known
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Rebuild every known match from its received events (restart recovery)."""
        for row in await asyncio.to_thread(self.repository.matches):
            match = LiveMatch(row, self.repository, max_calculations=self.max_calculations, dab=self.dab)
            await match.load()
            self.matches[match.match_id] = match

    def get(self, match_id):
        match = self.matches.get(match_id)
        if match is None or match.purged:
            raise RuleError('match_not_found', 'Unknown or finished-and-cleared match.', 404)
        return match

    async def require(self, match_id):
        """`get`, but a match whose MA1 has not arrived yet (not purged) is `match_not_started`."""
        if match_id not in self.matches and not await asyncio.to_thread(self.repository.tombstoned, match_id):
            raise RuleError('match_not_started', 'This match has not opened yet. It opens about a minute before kick-off.', 404)
        return self.get(match_id)

    async def accept_info(self, info):
        """MA1: store it (unless tombstoned or before a purge-all cut-off) and start tracking."""
        async with self._lock:
            known = info.matchId in self.matches
            accepted = known or await asyncio.to_thread(self.repository.accept_match, info)
            if accepted and not known:
                match = LiveMatch({'match_id': info.matchId, 'fixture': info.fixture},
                                  self.repository, max_calculations=self.max_calculations, dab=self.dab)
                self.matches[info.matchId] = match
                for callback in self.on_match:
                    callback(match)
            return accepted

    async def adopt(self, row):
        """Track a match already in the store, rebuilt from its received events as after a restart."""
        async with self._lock:
            if row['match_id'] in self.matches:
                return self.matches[row['match_id']]
            match = LiveMatch(row, self.repository, max_calculations=self.max_calculations, dab=self.dab)
            await match.load()
            self.matches[match.match_id] = match
            for callback in self.on_match:
                callback(match)
            return match

    async def accept_events(self, envelopes):
        """MatchEvent v2s of one match, in seq order; only for a match whose MA1 was stored."""
        match = self.matches.get(envelopes[0].matchId) if envelopes else None
        if match is None:
            return 0
        return await match.accept_batch([(e.seq, e.event) for e in envelopes])

    def gaps(self):
        """Missing seqs currently blocking a match."""
        now = time.monotonic()
        return [gap for match in self.matches.values() if (gap := match.gap(now))]

    async def recover_gaps(self, fetch, timeout, batch=GAP_BATCH):
        """Fill each seq missing for `timeout` seconds: ETL's canonical event when `fetch` finds it,
        else a placeholder. An unreachable ETL gets one more `timeout` before the seq is skipped. Once the first
        missing seq has timed out, the whole run of missing seqs before the first held event is filled in this
        pass (up to `batch`): a stream outage loses hundreds at once, and one per timeout would take hours."""
        for gap in self.gaps():
            if gap['age_seconds'] < timeout:
                continue
            match = self.matches.get(gap['match_id'])
            if match is None or match.purged:
                continue
            end = min(match.pending, default=gap['seq']) - 1 if match.pending else gap['seq']
            for seq in range(gap['seq'], min(end, gap['seq'] + batch - 1) + 1):
                if match.purged or match.seq + 1 != seq:
                    break  # purged, or it arrived meanwhile
                try:
                    event = await fetch(gap['match_id'], seq)
                except Exception:
                    if gap['age_seconds'] < 2 * timeout:
                        break
                    event = None
                await match.fill_gap(seq, event or match.placeholder(seq), 'recovered' if event else 'skipped',
                                     gap['age_seconds'])

    async def watch_gaps(self, fetch, config, interval=1.0):
        """Background loop: recover gaps older than the `stream` config's timeout."""
        while True:
            await asyncio.sleep(interval)
            try:
                await self.recover_gaps(fetch, (await config.get('stream')).gap_timeout_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('Gap recovery delayed', exc_info=True)

    async def checkpoint(self, checkpoint):
        await asyncio.to_thread(self.repository.checkpoint, *checkpoint)

    async def purge(self, match_id=None):
        """Tombstone, then delete this service's rows for one match (or all). Idempotent."""
        async with self._lock:
            targets = [self.matches[match_id]] if match_id in self.matches else (
                list(self.matches.values()) if match_id is None else [])
            for match in targets:
                await match.lock.acquire()
            try:
                ids, counts = await asyncio.to_thread(self.repository.purge, match_id)
                for match in targets:
                    match.purged = True
                    match.changed.set()
                    self.matches.pop(match.match_id, None)
            finally:
                for match in targets:
                    match.lock.release()
        for callback in self.on_purge:
            await callback(ids)
        log.info('Purged matches %s: %s', ids, counts)
        return {'match_ids': ids, 'purged': counts}
