"""Local-only fake ETL/narrative services. Neither is a production service implementation."""
import os

import httpx
from fastapi import FastAPI, HTTPException
from graphql import build_schema, graphql_sync
from pydantic import BaseModel, Field

from .domain import MatchEvent, Narrative, RuleError
from .fixtures import FixtureFeed


def normalise(raw, match_id):
    """Opta-inspired test shape, NOT a licensed Opta schema/parser."""
    if raw.get("matchId") != match_id:
        raise ValueError("Unknown match")
    qualifiers = {q["type"]: q["value"] for q in raw.get("qualifiers", [])}
    return MatchEvent(id=raw["eventId"], match_id=match_id, sequence=raw["sequence"],
                      minute=raw["timeMin"], team={"CHE": "home", "MUN": "away"}[raw["teamId"]],
                      type=raw["typeName"], body_part=qualifiers.get("bodyPart"),
                      related_event_id=qualifiers.get("relatedEventId"), key_moment=raw.get("keyMoment"))


class Query(BaseModel):
    query: str = Field(max_length=10000)
    variables: dict = Field(default_factory=dict)


def create_fake(role, notify_url=None):
    if role not in ("etl", "narrative"):
        raise ValueError("FAKE_ROLE must be etl or narrative")
    app = FastAPI(title=f"Synthetic {role} fixture service")
    feed = FixtureFeed("synthetic-demo", 3)
    app.state.feed = feed
    fields = "matchEvents(matchId: ID!): JSON matchState(matchId: ID!, team: String!): JSON" if role == "etl" else "context(matchId: ID!, bucket: String!): JSON"
    fields += " questionData(snapshotId: ID!, operation: String!, offset: Int, limit: Int, ids: [String!], tier: String, start: Int, end: Int, eventType: String, playerId: String, period: Int): JSON"
    schema = build_schema("scalar JSON\ntype Query {" + fields + "}")
    from .fake_question_data import FakeQuestionData
    question_data = FakeQuestionData(role)
    question_data.wire(app, schema)
    app.state.question_data = question_data
    schema.type_map["JSON"].serialize = lambda value: value

    def read_match(root, info, matchId):
        if matchId != feed.match_id:
            raise ValueError("Unknown match")
        return [e.model_dump() for e in sorted(feed.events.values(), key=lambda e: e.sequence)]

    def read_context(root, info, matchId, bucket):
        if matchId != feed.match_id or bucket not in feed.selections:
            raise ValueError("Unknown match or bucket")
        return {"stat_ids": feed.defaults(bucket), "narratives": feed.history(bucket), "synthetic": True}

    schema.query_type.fields["matchEvents" if role == "etl" else "context"].resolve = read_match if role == "etl" else read_context
    if role == "etl":
        def read_state(root, info, matchId, team):
            if matchId != feed.match_id or team not in ("home", "away", "neutral"):
                raise ValueError("Unknown match or team")
            return {"key_moments": feed.key_moments(),
                    "stats": {key: feed.value("default", key, team) for key in ("goals", "cards", "shots", "possession")}}
        schema.query_type.fields["matchState"].resolve = read_state

    @app.get("/health")
    async def health():
        return {"status": "ok", "role": role, "synthetic": True}

    @app.post("/graphql")
    async def query(body: Query):
        return graphql_sync(schema, body.query, variable_values=body.variables).formatted

    async def notify(path, payload):
        if notify_url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(notify_url + path, json=payload)
                    response.raise_for_status()
            except httpx.HTTPError as exc:
                raise HTTPException(502, "Fixture stored, but backend delivery failed; retry the replay") from exc

    if role == "etl":
        @app.post("/events", status_code=202)
        async def event(raw: dict):
            try:
                event = normalise(raw, feed.match_id)
                changed = feed.accept_event(event)
            except (KeyError, ValueError, TypeError, RuleError) as exc:
                raise HTTPException(422, str(exc)) from exc
            # Replay delivery even on duplicate: a previous notification may have failed.
            await notify("/dev/events", event.model_dump())
            return {"accepted": True, "duplicate": not changed, "synthetic": True}
    else:
        @app.post("/narratives", status_code=202)
        async def narrative(body: Narrative):
            try:
                feed.accept(body)
            except RuleError as exc:
                raise HTTPException(exc.status, exc.message) from exc
            await notify("/dev/narratives", body.model_dump())
            return {"accepted": True, "synthetic": True}
    return app


def from_env():
    return create_fake(os.environ["FAKE_ROLE"], os.environ.get("BACKEND_NOTIFY_URL"))
