"""ETL GraphQL client (Data API builder). Implements `match_data.MatchData`.

Filters are passed as GraphQL variables of DAB's generated `{Entity}FilterInput` types.
Clock bounds compare (periodId, timeMin, timeSec) lexicographically, because timeMin
repeats across periods (first-half added time and the second half both use 45+).
SPADL reads (`spadlActions`, `executeStatsAtSeq`) are bounded by a canonical seq and wait
until `matchWatermarks.spadlSeq` has reached it, so they never see a partial conversion.
MA3 reads (`rawEvents`) are bounded by seq as well as clock: `eventSeq <= matchWatermarks.seq`, the
ETL's committed canonical seq, so rows SQL holds past it are unreachable. A clock range that already
holds rows past the watermark is not complete yet: `events` and `event_seq` raise EtlBehind for it.
"""
import asyncio
import json

import httpx

from narrative_engine.core.models import MatchClock
from narrative_engine.context.render import ACTION_FIELDS, MatchInfo
from narrative_engine.match_data import EtlBehind

PAGE = 1000
STAT_FIELDS = "statId kind contestantId value available unit definition"
KEY_FIELDS = "id keyType detail typeId contestantId playerId periodId timeMin timeSec eventTime relatedEventId"
TREND_FIELDS = "trendId label meaning unit contestantId window minutes value baseline delta level change enabled"
SPELL_FIELDS = "trendId contestantId periodId fromLabel toLabel minutes ongoing enabled"


def trend_rows(rows):
    """trendsAtSeq rows in the engine's shape: `indicator label meaning unit contestantId window minutes value
    previous delta level trend`. Disabled trends are served without flags, as decoration; the engine leaves them out,
    so the analyst can neither see nor cite them."""
    return [{"indicator": r["trendId"], "label": r.get("label"), "meaning": r.get("meaning"), "unit": r.get("unit"),
             "contestantId": r["contestantId"], "window": r["window"],
             "minutes": r.get("minutes"), "value": r["value"], "previous": r.get("baseline"), "delta": r.get("delta"),
             "level": r.get("level"), "trend": r.get("change")} for r in rows if r.get("enabled", True)]


def spell_rows(rows):
    """trendSpellsAtSeq rows, enabled kinds only: `kind` (territory, pressure) and the served fields."""
    return [{"kind": r["trendId"].removesuffix("_spell"), "contestantId": r["contestantId"], "periodId": r["periodId"],
             "fromLabel": r["fromLabel"], "toLabel": r["toLabel"], "minutes": r["minutes"], "ongoing": r["ongoing"]}
            for r in rows if r.get("enabled", True)]


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

    async def watermark(self, match_id):
        """matchWatermarks {seq, spadlSeq}: the committed canonical seq and the SPADL conversion's."""
        rows = await self._items("matchWatermarks", "MatchWatermark", {"matchId": {"eq": match_id}}, "seq spadlSeq",
                                 first=1)
        return {k: rows[0][k] or 0 for k in ("seq", "spadlSeq")} if rows else {"seq": 0, "spadlSeq": 0}

    async def _committed(self, match_id, *conditions, complete=False):
        """Filter for MA3 rows matching `conditions` up to the committed seq. With `complete`, raises
        EtlBehind while matching rows past it exist (the range is still being written)."""
        seq = (await self.watermark(match_id))["seq"]
        if complete and await self._items("rawEvents", "RawEvent", match(match_id, *conditions, {"eventSeq": {"gt": seq}}),
                                          "id", first=1):
            raise EtlBehind(f"{match_id}: MA3 rows past the committed seq {seq} are not complete yet")
        return match(match_id, *conditions, {"eventSeq": {"lte": seq}})

    async def events(self, match_id, start, end, until_sec=59):
        bound = await self._committed(match_id, at_or_after(start), at_or_before(end, until_sec), complete=True)
        rows = await self._items("rawEvents", "RawEvent", bound, "payload")
        return sorted((json.loads(r["payload"]) for r in rows), key=lambda e: e["seq"])

    async def spadl_seq(self, match_id):
        return (await self.watermark(match_id))["spadlSeq"]

    async def _converted(self, match_id, seq):
        """Wait briefly until the SPADL post-processor has converted through `seq` (it trails by a poll)."""
        for attempt in range(self.retries + 1):
            if await self.spadl_seq(match_id) >= seq:
                return
            if attempt < self.retries:
                await asyncio.sleep(self.stats_wait * 2 ** attempt)
        raise EtlBehind(f"{match_id}: SPADL actions are not converted through seq {seq} yet")

    async def actions(self, match_id, after_seq, seq):
        if not seq or seq <= after_seq:
            return []
        await self._converted(match_id, seq)
        return await self._items("spadlActions", "SpadlAction",
                                 match(match_id, {"finalSeq": {"gt": after_seq}}, {"finalSeq": {"lte": seq}}),
                                 ACTION_FIELDS, order="{actionId: ASC}")

    async def _at_seq(self, procedure, fields, match_id, seq, never_empty=True):
        """A snapshot procedure's rows at canonical `seq`, once SPADL is converted through it. With
        `never_empty`, [] means the procedure's own watermark check trails: retry, then EtlBehind."""
        if not seq:
            return []
        await self._converted(match_id, seq)
        query = f"query ($m: String!, $s: Int!) {{ {procedure}(matchId: $m, seq: $s) {{ {fields} }} }}"
        for attempt in range(self.retries + 1):
            rows = (await self._post(query, {"m": match_id, "s": seq}))[procedure]
            if rows or not never_empty:
                return rows
            if attempt < self.retries:
                await asyncio.sleep(self.stats_wait * 2 ** attempt)
        raise EtlBehind(f"{match_id}: {procedure}({seq}) is empty")

    async def stats_at(self, match_id, seq):
        return await self._at_seq("executeStatsAtSeq", STAT_FIELDS, match_id, seq)

    async def trends_at(self, match_id, seq):
        """Trend indicators at `seq` (local/contracts.md §4b), normalised (`trend_rows`)."""
        return trend_rows(await self._at_seq("executeTrendsAtSeq", TREND_FIELDS, match_id, seq))

    async def spells_at(self, match_id, seq):
        """Territory and pressure spells up to `seq`; [] is a real answer (none, or disabled)."""
        return spell_rows(await self._at_seq("executeTrendSpellsAtSeq", SPELL_FIELDS, match_id, seq,
                                             never_empty=False))

    async def event_seq(self, match_id, until, until_sec=59):
        """The canonical seq of the latest MA3 row up to `until`:`until_sec` (MA3 `eventSeq`), or None."""
        bound = await self._committed(match_id, at_or_before(until, until_sec), complete=True)
        rows = await self._items("rawEvents", "RawEvent", bound, "eventSeq", order="{seq: DESC}", first=1)
        return rows[0]["eventSeq"] if rows else None

    async def event_seq_of(self, match_id, event_id):
        """None until the row is committed (eventSeq <= the watermark)."""
        rows = await self._items("rawEvents", "RawEvent", await self._committed(match_id, {"id": {"eq": event_id}}),
                                 "eventSeq", first=1)
        return rows[0]["eventSeq"] if rows else None

    async def key_events(self, match_id, until, until_sec=59):
        return await self._items("keyEvents", "KeyEvent", match(match_id, at_or_before(until, until_sec)), KEY_FIELDS)

    async def period_end(self, match_id, period_id):
        end = await self.period_end_at(match_id, period_id)
        return end and end[0]

    async def period_end_at(self, match_id, period_id):
        rows = await self._items("rawEvents", "RawEvent",
                                 await self._committed(match_id, {"periodId": {"eq": period_id}}, {"typeId": {"eq": 30}}),
                                 "periodId timeMin timeSec", first=1)
        return (MatchClock(rows[0]["periodId"], rows[0]["timeMin"]), rows[0]["timeSec"]) if rows else None

    async def raw_event(self, match_id, contestant_id, event_id):
        rows = await self._items("rawEvents", "RawEvent",
                                 match(match_id, {"contestantId": {"eq": contestant_id}}, {"eventId": {"eq": event_id}}),
                                 "payload", first=1)
        return json.loads(rows[0]["payload"]) if rows else None
