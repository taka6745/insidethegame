"""Archive before publishing; one ordered match cursor and shared audience refresh."""
import asyncio
import hashlib
import json
from datetime import datetime

from ..models.brokers import BucketNarratives
from ..models.snapshots import SnapshotInput


class NarrativeDelivery:
    def __init__(self, service, publisher):
        self.service, self.publisher = service, publisher
        saved = service.repository.delivery_state()
        self.latest = SnapshotInput.model_validate(saved['metadata']) if saved else None
        self.signature = saved['signature'] if saved else None
        self.lock = asyncio.Lock()

    def stale(self, metadata):
        if self.latest is None:
            return False
        previous, incoming = self.latest.snapshot, metadata.snapshot
        if incoming.run_id == previous.run_id:
            return (incoming.cursor, incoming.period or 0, incoming.clock_seconds or 0) < (
                previous.cursor, previous.period or 0, previous.clock_seconds or 0)
        return datetime.fromisoformat(incoming.captured_at.replace('Z', '+00:00')) <= datetime.fromisoformat(previous.captured_at.replace('Z', '+00:00'))

    async def capture(self, metadata):
        async with self.lock:
            if self.stale(metadata):
                # Out-of-order history is useful to questions, but cannot move the
                # live audience cursor backwards or publish stale bucket content.
                try:
                    self.service.repository.read(metadata.snapshot.id)
                except KeyError:
                    await self.service.capture(metadata, viewer=False)
                return
            await self._publish(metadata, force=True)

    async def refresh(self):
        async with self.lock:
            if self.latest is not None:
                await self._publish(self.latest)

    async def _publish(self, metadata, *, force=False):
        await self.service.capture(metadata, viewer=True)
        document = self.service.read(metadata.snapshot.id, 'viewer')
        message = BucketNarratives(snapshot=metadata.snapshot, items=document['items'],
                                   events=document['events'], audience_revision=document['audience_revision'])
        body = message.model_dump(mode='json')
        # Capture timestamps are transport metadata, not new commentary.
        signature_body = {**body, 'snapshot': metadata.snapshot.model_dump(exclude={'captured_at'})}
        signature = hashlib.sha256(json.dumps(signature_body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if force or signature != self.signature:
            await self.publisher.send(body, signature)
        self.service.repository.save_delivery_state(metadata.model_dump(mode='json'), signature)
        self.latest, self.signature = metadata, signature
