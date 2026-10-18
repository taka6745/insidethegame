"""Replaceable read contracts. Production adapters must preserve snapshot watermarks."""
from typing import Protocol
import httpx
from backend.domain import RuleError
from backend.models.questions import SnapshotInput

class MatchDataClient(Protocol):
    async def capture(self, payload: SnapshotInput): ...
    async def stats(self, snapshot): ...
    async def events(self, snapshot, **filters): ...

class NarrativeClient(Protocol):
    async def capture(self, payload: SnapshotInput): ...
    async def compact(self, snapshot): ...
    async def recaps(self, snapshot, **filters): ...

class GraphQLQuestionData:
    """Allowlisted GraphQL operations; the model never supplies query text or URLs."""
    def __init__(self, url, *, bridge=False, transport=None):
        self.url, self.bridge, self.transport = url, bridge, transport
        self.audience_dependent = bridge == "demo"

    async def capture(self, payload, *, purpose="question"):
        if not self.bridge:
            raise RuleError('snapshot_unavailable', 'Sorry, match snapshots are not available.', 503)
        async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
            prefix = '/demo' if self.bridge == 'demo' else '/dev'
            path = prefix + ('/viewer-snapshots' if purpose == 'viewer' else '/question-snapshots')
            body = payload.model_dump(mode='json')
            if self.bridge == 'demo':
                # ETL owns the recording. A checkpoint identifies an observed
                # prefix; user-backend never sends history back as the source.
                body['events'] = []
            response = await client.post(self.url.rsplit('/', 1)[0] + path, json=body)
            response.raise_for_status()
            if response.json().get('snapshot_id') != payload.snapshot.id:
                raise ValueError('Wrong snapshot acknowledged')

    async def read(self, snapshot, operation, **filters):
        query = '''query QuestionData($snapshotId:ID!,$operation:String!,$offset:Int,$limit:Int,$ids:[String!],$tier:String,$start:Int,$end:Int,$eventType:String,$playerId:String,$period:Int) {
          questionData(snapshotId:$snapshotId,operation:$operation,offset:$offset,limit:$limit,ids:$ids,tier:$tier,start:$start,end:$end,eventType:$eventType,playerId:$playerId,period:$period)
        }'''
        variables = {'snapshotId': snapshot.id, 'operation': operation, **filters}
        async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
            response = await client.post(self.url, json={'query': query, 'variables': variables})
            response.raise_for_status()
            body = response.json()
        if body.get('errors'):
            raise ValueError('Upstream snapshot is unavailable')
        result = body['data']['questionData']
        if result.get('snapshot_id') != snapshot.id or result.get('match_id') != snapshot.match_id:
            raise ValueError('Wrong upstream snapshot or match')
        if not result.get('complete'):
            raise ValueError('Incomplete upstream snapshot')
        return result

    async def stats(self, snapshot):
        return await self.read(snapshot, 'stats')

    async def events(self, snapshot, **filters):
        return await self.read(snapshot, 'events', **filters)

    async def compact(self, snapshot):
        return await self.read(snapshot, 'compact')

    async def recaps(self, snapshot, **filters):
        return await self.read(snapshot, 'recaps', **filters)
