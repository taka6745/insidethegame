"""One demo publisher/consumer owner. Replay advances only on Event Hubs receipt."""
import asyncio
from contextlib import suppress
from .question_snapshot import build_snapshot


class BrokerRuntime:
    def __init__(self, lab, transport, inbox, *, timeout=30):
        self.lab, self.transport, self.inbox = lab, transport, inbox
        self.timeout = timeout
        self._tasks = []
        self._publish_lock = asyncio.Lock()
        self._accepted = asyncio.Condition()
        self._published = None
        self.on_narrative = None

    async def start(self):
        await asyncio.to_thread(self.inbox.initialize)
        await self.transport.open()
        self.lab.broker = self
        self._tasks = [asyncio.create_task(self.transport.events(self.accept_event)),
                       asyncio.create_task(self.transport.narratives(self.accept_narrative))]

    async def close(self):
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        await self.transport.close()

    async def prepare(self, payload):
        """Publish initial/reset/final watermark; questions never call this method."""
        async with self._publish_lock:
            if self._published != payload.snapshot.id:
                await self.transport.publish(payload)
                self._published = payload.snapshot.id

    async def advance(self, *, finish=True):
        async with self._publish_lock:
            async with self.lab._lock:
                lab = self.lab
                event = lab.source.next_event(lab.position)
                if event is None:
                    return False
                cursor, run_id = lab.position + 1, str(lab.run_id)
                payload = build_snapshot(lab.source, run_id, cursor,
                    finished=finish and cursor == len(lab.source.events))
            await self.transport.publish(payload, event)
            self._published = payload.snapshot.id
        async with asyncio.timeout(self.timeout), self._accepted:
            await self._accepted.wait_for(lambda: str(lab.run_id) != run_id or lab.position >= cursor)
        if str(lab.run_id) != run_id:
            return False
        return lab.position < len(lab.source.events)

    async def accept_event(self, delivery):
        if delivery.event is None:
            return  # Recovery watermark does not advance the calculation index.
        # Source order, revision and run guards live alongside the durable cursor.
        await self.lab.accept_event(delivery=delivery, finish=not self.lab.source.timed)
        async with self._accepted:
            self._accepted.notify_all()

    async def accept_narrative(self, delivery):
        async with self.lab._lock:
            if delivery.snapshot.run_id != str(self.lab.run_id):
                return
            if delivery.snapshot.match_id != self.lab.source.match_id or delivery.snapshot.recording_hash != self.lab.source.fingerprint:
                raise ValueError('Wrong narrative source')
            # Persist even if ETL wins the race with this process's event consumer.
            # Product only reads a snapshot matching its own committed cursor.
            changed = await asyncio.to_thread(self.inbox.save, delivery)
        if changed:
            if self.on_narrative:
                self.on_narrative()
            self.lab.changed.set()
