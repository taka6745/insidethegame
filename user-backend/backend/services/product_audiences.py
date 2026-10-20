"""Publish the union of connected viewer choices, once per presence change.

The demo has one API owner. Startup clears its persisted flags; a distributed
deployment needs expiring shared presence leases instead of this local registry.
"""
import asyncio


class ProductAudiences:
    def __init__(self, repository, live):
        self.repository, self.live = repository, live
        self.match_id = self.run_id = None
        self._published = None
        self._lock = asyncio.Lock()

    async def initialize(self, match_id, run_id):
        await asyncio.to_thread(self.repository.clear_viewer_targets)
        await self.match(match_id, run_id)

    async def match(self, match_id, run_id):
        async with self._lock:
            if self.match_id and self.match_id != match_id:
                await asyncio.to_thread(self.repository.set_viewer_targets, self.match_id, set())
            self.match_id, self.run_id = match_id, run_id
            await self._sync()

    async def sync(self):
        async with self._lock:
            await self._sync()

    async def _sync(self):
        choices = {(peer.viewer['audience']['team'], peer.viewer['audience']['fan_style'])
                   for peer in self.live.active() if peer.viewer['run_id'] == self.run_id}
        current = self.match_id, frozenset(choices)
        if current != self._published:
            await asyncio.to_thread(self.repository.set_viewer_targets, self.match_id, choices)
            self._published = current
