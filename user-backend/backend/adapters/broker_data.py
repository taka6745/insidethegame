"""Read-only GraphQL snapshots and broker-delivered live narrative documents."""
import asyncio
import httpx
from backend.domain import RuleError
from .question_data import GraphQLQuestionData


class BrokerQuestionData(GraphQLQuestionData):
    def __init__(self, url, *, operation, inbox=None, timeout=30, transport=None):
        super().__init__(url, transport=transport)
        self.operation, self.inbox, self.timeout = operation, inbox, timeout
        self.audience_dependent = inbox is not None

    async def capture(self, payload, *, purpose='question'):
        # The shared publisher owns progression. Asking a question cannot publish
        # events, request narrative generation or move an upstream watermark.
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    try:
                        await self.read(payload.snapshot, self.operation)
                        return
                    except (ValueError, OSError, httpx.HTTPError):
                        await asyncio.sleep(.1)
        except TimeoutError as exc:
            raise RuleError('snapshot_unavailable', 'The match feed is catching up. Please try again.', 503) from exc

    async def read(self, snapshot, operation, **filters):
        if operation != 'viewer' or self.inbox is None:
            return await super().read(snapshot, operation, **filters)
        async with asyncio.timeout(self.timeout):
            while True:
                document = await asyncio.to_thread(self.inbox.read, snapshot.id)
                if document:
                    if document['match_id'] != snapshot.match_id:
                        raise ValueError('Wrong narrative match')
                    return document
                await asyncio.sleep(.1)
