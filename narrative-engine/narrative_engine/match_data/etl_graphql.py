"""ETL GraphQL client (Data API builder). Implements `fixture.MatchData`.

Filters are passed as GraphQL variables of DAB's generated `{Entity}FilterInput` types.
Clock bounds compare (periodId, timeMin, timeSec) lexicographically, because timeMin
repeats across periods (first-half added time and the second half both use 45+).
"""
import asyncio
import json

import httpx

from narrative_engine.core.models import MatchClock
from narrative_engine.context.render import MatchInfo

PAGE = 1000
STAT_FIELDS = ("matchId contestantId position periodId timeMin minuteLabel goals ownGoals passes passesCompleted "
               "shots shotsOnTarget corners fouls yellowCards redCards events possessionPct")
KEY_FIELDS = "id keyType detail typeId contestantId playerId periodId timeMin timeSec eventTime relatedEventId"


class GraphQLError(RuntimeError):
    pass


def at_or_after(clock):
    return {"or": [{"periodId": {"gt": clock.periodId}},
                   {"and": [{"periodId": {"eq": clock.periodId}}, {"timeMin": {"gte": clock.timeMin}}]}]}


def at_or_before(clock, second=None):
    same_minute = [{"timeMin": {"eq": clock.timeMin}}] + ([{"timeSec": {"lte": second}}] if second is not None else [])
    return {"or": [{"periodId": {"lt": clock.periodId}},
                   {"and": [{"periodId": {"eq": clock.periodId}}, {"timeMin": {"lt": clock.timeMin}}]},
                   {"and": [{"periodId": {"eq": clock.periodId}}] + same_minute}]}


def match(match_id, *conditions):
    return {"and": [{"matchId": {"eq": match_id}}, *conditions]}


class GraphQLMatchData:
    def __init__(self, url, client=None, retries=3, stats_wait=0.5):
        self.url = url
        self.client = client or httpx.AsyncClient(timeout=30)
        self.retries, self.stats_wait = retries, stats_wait
        self._info = {}

    async def aclose(self):
        await self.client.aclose()

    async def _post(self, query, variables):
        for attempt in range(self.retries + 1):
            try:
                response = await self.client.post(self.url, json={"query": query, "variables": variables})
                body = response.json()  # validation errors arrive as HTTP 400 with a GraphQL body
                break
            except (httpx.TransportError, json.JSONDecodeError):
                if attempt == self.retries:
                    raise
                await asyncio.sleep(0.5 * 2 ** attempt)
        if body.get("errors"):
            raise GraphQLError(json.dumps(body["errors"])[:2000])
        return body["data"]

    async def _items(self, entity, type_name, filter, fields, order=None, first=None):
        """All matching rows, following DAB's cursor pagination unless `first` caps them."""
        order_arg = f", orderBy: {order}" if order else ""
        query = (f"query ($f: {type_name}FilterInput, $first: Int, $after: String) {{ "
                 f"{entity}(filter: $f, first: $first, after: $after{order_arg}) {{ "
                 f"items {{ {fields} }} hasNextPage endCursor }} }}")
        items, after = [], None
        while True:
            page = (await self._post(query, {"f": filter, "first": first or PAGE, "after": after}))[entity]
            items += page["items"]
            if first or not page["hasNextPage"]:
                return items
            after = page["endCursor"]

    async def match_info(self, match_id):
        if match_id not in self._info:
            rows = await self._items("matches", "Match", match(match_id), "payload", first=1)
            if not rows:
                raise LookupError(f"match {match_id} is not in the ETL database yet")
            self._info[match_id] = MatchInfo.from_ma1(json.loads(rows[0]["payload"]))
        return self._info[match_id]

    async def events(self, match_id, start, end, until_sec=59):
        rows = await self._items("rawEvents", "RawEvent", match(match_id, at_or_after(start), at_or_before(end, until_sec)),
                                 "payload")
        return sorted((json.loads(r["payload"]) for r in rows), key=lambda e: e["seq"])

    async def stats_as_of(self, match_id, clock, expect_row=False):
        """Latest rows at or before `clock`. With `expect_row` (the minute had events), wait
        briefly for that minute's row, since the SQL write can trail its MinuteClosed."""
        for attempt in range(self.retries + 1):
            rows = await self._items("matchStatsAsOfs", "MatchStatsAsOf", match(match_id, at_or_before(clock)),
                                     STAT_FIELDS, order="{periodId: DESC, timeMin: DESC}", first=2)
            current = rows and MatchClock(rows[0]["periodId"], rows[0]["timeMin"]) == clock
            if current or not expect_row or attempt == self.retries:
                return rows
            await asyncio.sleep(self.stats_wait * 2 ** attempt)

    async def key_events(self, match_id, until, until_sec=59):
        return await self._items("keyEvents", "KeyEvent", match(match_id, at_or_before(until, until_sec)), KEY_FIELDS)

    async def period_end(self, match_id, period_id):
        rows = await self._items("rawEvents", "RawEvent",
                                 match(match_id, {"periodId": {"eq": period_id}}, {"typeId": {"eq": 30}}),
                                 "periodId timeMin", first=1)
        return MatchClock(rows[0]["periodId"], rows[0]["timeMin"]) if rows else None

    async def raw_event(self, match_id, contestant_id, event_id):
        rows = await self._items("rawEvents", "RawEvent",
                                 match(match_id, {"contestantId": {"eq": contestant_id}}, {"eventId": {"eq": event_id}}),
                                 "payload", first=1)
        return json.loads(rows[0]["payload"]) if rows else None
