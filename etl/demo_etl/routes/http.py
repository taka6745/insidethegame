"""HTTP and GraphQL transport only; services own reads and publication."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from graphql import build_schema, graphql_sync
from pydantic import BaseModel, Field
from demo_etl.models.snapshot import SnapshotInput


class Query(BaseModel):
    query: str = Field(max_length=10000)
    variables: dict = Field(default_factory=dict)


def create_app(service, *, brokers=None):
    @asynccontextmanager
    async def lifespan(app):
        if brokers:
            await brokers.start()
        try:
            yield
        finally:
            if brokers:
                await brokers.close()

    app = FastAPI(lifespan=lifespan, title='Demo ETL — persisted match history and standard stats')
    schema = build_schema('''scalar JSON
      type Query {
        questionData(snapshotId: ID!, operation: String!, offset: Int, limit: Int, ids: [String!], tier: String, start: Int, end: Int, eventType: String, playerId: String, period: Int): JSON
        matchEvents(matchId: ID!): JSON
        matchState(matchId: ID!, team: String!): JSON
      }''')
    schema.type_map['JSON'].serialize = lambda value: value
    schema.query_type.fields['questionData'].resolve = lambda root, info, snapshotId, operation, **filters: service.read(snapshotId,operation,**filters)
    schema.query_type.fields['matchEvents'].resolve = lambda root, info, matchId: [e.model_dump(mode='json') for e in service.payload(service.history.latest(matchId).snapshot.id).events]

    def match_state(root, info, matchId, team):
        payload = service.history.latest(matchId)
        teams = {'home':payload.teams[0]['id'],'away':payload.teams[1]['id'],'neutral':None}
        if team not in teams:
            raise ValueError('Unknown team perspective')
        stats = service.read(payload.snapshot.id,'stats')['stats']
        return {'stats':{s['id'].split(':',1)[1]:s['value'] for s in stats if s['team_id']==teams[team] and s['available']},'key_moments':[]}
    schema.query_type.fields['matchState'].resolve = match_state

    @app.get('/health')
    def health():
        return {'status':'ok','role':'demo-etl','synthetic':True,'history_store':'postgresql-local-substitute','stats_store':'postgresql-local-substitute',
                **(brokers.status() if brokers else {'transport':'http-fixture'})}

    @app.post('/graphql')
    def graphql(body: Query):
        result = graphql_sync(schema,body.query,variable_values=body.variables)
        output = {'data':result.data}
        if result.errors:
            # Do not expose driver errors or database connection strings.
            output['errors'] = [{'message':'ETL snapshot read unavailable or invalid query'} for _ in result.errors]
        return output

    @app.get('/demo/recording')
    def recording():
        if not service.recording:
            raise HTTPException(503,'Demo recording is not configured')
        return Response(service.recording.content,media_type='application/json')

    def publish(payload, owned):
        if brokers:
            raise HTTPException(409,'Snapshots are published through Event Hubs')
        try:
            return service.publish(payload,owned=owned)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc

    @app.post('/demo/snapshots')
    @app.post('/demo/viewer-snapshots')
    @app.post('/demo/question-snapshots')
    def demo_snapshot(payload: SnapshotInput):
        return publish(payload,True)

    @app.get('/demo/snapshots/{snapshot_id}')
    def read_snapshot(snapshot_id: str):
        try:
            return service.payload(snapshot_id)
        except KeyError as exc:
            raise HTTPException(404,'Snapshot unavailable') from exc

    @app.post('/dev/viewer-snapshots')
    @app.post('/dev/question-snapshots')
    def compatibility_snapshot(payload: SnapshotInput):
        return publish(payload,False)
    return app
