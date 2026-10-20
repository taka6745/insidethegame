"""Transport only: checkpoint metadata in, bounded GraphQL reads out."""
import httpx
from fastapi import APIRouter, HTTPException
from graphql import build_schema, graphql_sync

from ..models.snapshots import GraphQLQuery, SnapshotInput


def routes(service, *, broker_enabled=False):
    router = APIRouter()
    # Authored reads are bounded by the requested snapshot's observed cursor.
    schema = build_schema('''scalar JSON
        type Query { questionData(snapshotId:ID!, operation:String!, offset:Int, limit:Int,
        ids:[String!], tier:String, start:Int, end:Int, eventType:String, playerId:String, period:Int):JSON
        keyMoments(snapshotId:ID!, offset:Int, limit:Int, period:Int):JSON
        minuteRecaps(snapshotId:ID!, offset:Int, limit:Int, ids:[String!], period:Int):JSON
        tierRecaps(snapshotId:ID!, offset:Int, limit:Int, ids:[String!], tier:String, period:Int):JSON
        narrativeContext(snapshotId:ID!):JSON }''')
    schema.type_map['JSON'].serialize = lambda value: value
    fields = schema.query_type.fields
    fields['questionData'].resolve = lambda root, info, snapshotId, operation, **filters: service.read(snapshotId, operation, **filters)
    for name, operation in (('keyMoments', 'key_moments'), ('minuteRecaps', 'minute_recaps'),
                            ('tierRecaps', 'tier_recaps'), ('narrativeContext', 'context')):
        fields[name].resolve = lambda root, info, snapshotId, operation=operation, **filters: service.read(snapshotId, operation, **filters)

    @router.get('/health')
    async def health():
        return {'status': 'ok', 'role': 'narrative', 'mode': 'authored-demo-stub',
                'transport': 'service-bus' if broker_enabled else 'http-fixture',
                'authored_minutes': len(service.commentary.document.minutes), 'synthetic': True}

    async def capture(body, viewer):
        if broker_enabled:
            raise HTTPException(409, 'Snapshots arrive through Service Bus in broker mode')
        if body.events:
            raise HTTPException(422, 'Send checkpoint metadata; events are owned by ETL')
        try:
            return await service.capture(body, viewer=viewer)
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, 'The narrative checkpoint is unavailable or inconsistent') from exc
        except httpx.HTTPError as exc:
            raise HTTPException(503, 'The ETL or audience service is unavailable; retry this checkpoint') from exc

    @router.post('/demo/viewer-snapshots')
    async def viewer(body: SnapshotInput):
        return await capture(body, True)

    @router.post('/demo/question-snapshots')
    async def question(body: SnapshotInput):
        return await capture(body, False)

    @router.post('/graphql')
    async def query(body: GraphQLQuery):
        return graphql_sync(schema, body.query, variable_values=body.variables).formatted

    return router
