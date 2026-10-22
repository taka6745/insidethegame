"""Event Hubs `match-events` producer: one partition key per match, batches split when full."""
import asyncio
import json


class SendError(Exception):
    """A send failed after its first `sent` bodies went out; `throttled`: the hub asked the client to slow down."""

    def __init__(self, sent, throttled):
        super().__init__(f"{'throttled' if throttled else 'failed'} after {sent} sent")
        self.sent, self.throttled = sent, throttled


class EventHubsSink:
    def __init__(self, connection_string, hub="match-events"):
        self.connection_string, self.hub, self.producer = connection_string, hub, None
        self._lock = asyncio.Lock()  # The SDK client is not coroutine-safe; runs share it.

    async def open(self):
        from azure.eventhub.aio import EventHubProducerClient
        self.producer = EventHubProducerClient.from_connection_string(
            self.connection_string, eventhub_name=self.hub, retry_total=3)

    async def close(self):
        if self.producer:
            await self.producer.close()

    async def send(self, partition_key, bodies):
        async with self._lock:
            await self._send(partition_key, bodies)

    async def _send(self, partition_key, bodies):
        from azure.eventhub import EventData
        sent = 0

        async def flush(batch):
            nonlocal sent
            try:
                await self.producer.send_batch(batch)
            except Exception as exc:  # The SDK's own retries are spent; the caller resends from `sent`.
                raise SendError(sent, getattr(exc, "error", None) == "server-busy" or "server-busy" in str(exc)) from exc
            sent += len(batch)

        batch = await self.producer.create_batch(partition_key=partition_key)
        for body in bodies:
            data = EventData(json.dumps(body, ensure_ascii=False, separators=(",", ":")))
            try:
                batch.add(data)
            except ValueError:  # Full: send in order, start the next batch.
                await flush(batch)
                batch = await self.producer.create_batch(partition_key=partition_key)
                batch.add(data)
        if len(batch):
            await flush(batch)
