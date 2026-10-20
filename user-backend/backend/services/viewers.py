"""Viewer sessions, cards and bucket delivery for the single-process harness."""
import asyncio
import hashlib
from collections import OrderedDict

from backend.domain import RuleError, card_ids, pin
from .live_viewers import LiveViewers


class ViewerService:
    def __init__(self, repository, feed, match_id, slots, *, receipt_capacity=10000):
        self.repository, self.feed = repository, feed
        self.match_id, self.slots = match_id, slots
        self.live = LiveViewers()
        if receipt_capacity < 1:
            raise ValueError('Receipt capacity must be positive')
        self._narrative_receipts = OrderedDict()
        self._receipt_capacity = receipt_capacity
        self._events_pending = False
        # Serialise state changes and fanout so a preference change cannot receive
        # a later message for the old bucket. Model work never takes this lock.
        self._lock = asyncio.Lock()

    async def profiles(self):
        return {'profiles': await asyncio.to_thread(self.repository.profiles), 'mode': 'fixture'}

    async def ready(self):
        await asyncio.to_thread(self.repository.ready)
        return {'status': 'ready', 'mode': 'fixture'}

    def calculations(self):
        return {'mode': 'fixture', 'match_id': self.match_id, 'calculations': self.feed.calculations}

    def _snapshot(self, viewer, view):
        state = viewer['state']
        cards = [{'kind': kind, 'id': key, 'value': view['values'][kind][key]}
                 for kind, key in card_ids(view['defaults'], state['pins'], self.slots)]
        return {'mode': 'fixture', 'synthetic': True, 'match_id': self.match_id,
                'profile_id': viewer['profile_id'], 'bucket': self.live.bucket(viewer),
                'cards': cards, 'pins': state['pins'], 'narratives': view['narratives'],
                'key_moments': view['key_moments']}

    async def _view(self, viewer):
        state = viewer['state']
        view = await asyncio.to_thread(self.feed.view, self.live.bucket(viewer), state['team'], state['pins'])
        return self._snapshot(viewer, view)

    async def snapshot(self, token):
        viewer = await asyncio.to_thread(self.repository.read, token, self.match_id)
        return await self._view(viewer)

    async def start(self, profile_id):
        async with self._lock:
            viewer = await asyncio.to_thread(self.repository.start, self.match_id, profile_id)
            self.live.replace_profile(profile_id)
            return {'session_token': str(viewer['token']), 'snapshot': await self._view(viewer)}

    async def attach(self, token):
        async with self._lock:
            viewer = await asyncio.to_thread(self.repository.read, token, self.match_id)
            snapshot = await self._view(viewer)
            return self.live.attach(token, viewer), snapshot

    async def _change(self, token, update, reason):
        async with self._lock:
            viewer = await asyncio.to_thread(self.repository.change, token, self.match_id, update)
            self.live.update(token, viewer)
            snapshot = await self._view(viewer)
            if peer := self.live.peers.get(token):
                peer.offer({'type': 'snapshot', 'reason': reason, 'data': snapshot})
            return snapshot

    async def preferences(self, token, preferences):
        return await self._change(token, lambda state: state.update(preferences.model_dump()), 'preferences_changed')

    async def add_pin(self, token, calculation_id, replace=None):
        self.feed.calculation(calculation_id)
        def update(state):
            state['pins'] = pin(state['pins'], calculation_id, self.slots, replace)
        return await self._change(token, update, 'pins_changed')

    async def remove_pin(self, token, calculation_id):
        def update(state):
            if calculation_id not in state['pins']:
                raise RuleError('pin_not_found', 'This statistic is not pinned', 404)
            state['pins'].remove(calculation_id)
        return await self._change(token, update, 'pins_changed')

    async def _broadcast(self, reason, narrative=None):
        groups = {}
        for peer in self.live.active(narrative.bucket if narrative else None):
            groups.setdefault(self.live.bucket(peer.viewer), []).append(peer)
        first_error = None
        for bucket, peers in groups.items():
            # Shared data is fetched once per bucket/update, regardless of viewers.
            # Custom fixture pins are unioned, while each viewer keeps their own order.
            pins = sorted({pin for peer in peers for pin in peer.viewer['state']['pins']})
            try:
                view = await asyncio.to_thread(self.feed.view, bucket, peers[0].viewer['state']['team'], pins)
            except RuleError as exc:
                first_error = first_error or exc
                for peer in peers:
                    peer.offer({'type': 'error', 'code': exc.code, 'detail': exc.message})
                continue
            for peer in peers:
                if narrative:
                    peer.offer({'type': 'narrative', 'data': narrative.model_dump(), 'synthetic': True})
                peer.offer({'type': 'snapshot', 'reason': reason, 'data': self._snapshot(peer.viewer, view)})
        if first_error:
            raise first_error

    async def deliver_narrative(self, narrative):
        async with self._lock:
            digest = hashlib.sha256(narrative.model_dump_json().encode()).hexdigest()
            receipt = self._narrative_receipts.get(narrative.id)
            if receipt is not None and receipt[0] != digest:
                raise RuleError('narrative_conflict', 'A narrative ID cannot change its payload', 422)
            if receipt is not None and receipt[1]:
                return {'accepted': True, 'duplicate': True, 'mode': 'fixture'}
            if receipt is None:
                if len(self._narrative_receipts) >= self._receipt_capacity:
                    completed = next((key for key, (_, delivered) in self._narrative_receipts.items() if delivered), None)
                    if completed is None:
                        raise RuleError('delivery_capacity', 'Pending narrative delivery is full; retry shortly', 503)
                    self._narrative_receipts.pop(completed)
                self.feed.accept(narrative)
                self._narrative_receipts[narrative.id] = (digest, False)
            # A failed upstream read can retry without appending the narrative again.
            # No awaits occur between the first enqueue and marking it delivered.
            await self._broadcast('narrative_received', narrative)
            self._narrative_receipts[narrative.id] = (digest, True)
            self._narrative_receipts.move_to_end(narrative.id)
        return {'accepted': True, 'duplicate': False, 'mode': 'fixture'}

    async def accept_event(self, event):
        async with self._lock:
            changed = self.feed.accept_event(event)
            self._events_pending = self._events_pending or changed
            if self._events_pending:
                # A retry after a failed fanout must still refresh cards, even
                # though the event itself has already been applied exactly once.
                await self._broadcast('match_event')
                self._events_pending = False
        return {'accepted': True, 'duplicate': not changed, 'mode': 'fixture'}
